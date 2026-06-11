"""
AIHub — Chat engine (event-stream API).

Pure streaming engine that drives one assistant turn (text + N tool rounds).
Consumed by both the CLI subcommand (`aihub chat <model>` via chat_cli.py)
and the Textual TUI (via tui/workers.py).

This module does NOT print, NOT prompt, NOT save automatically. It yields
typed events and mutates the messages list in place. Callers decide how to
render and when to persist.
"""
from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, Iterator, List, Optional, Union

from .history import save_session
from .memory import build_system_prompt
from .tools import run_tool, wants_tools, TOOLS_SCHEMA


def _truncate(text: str, max_chars: int = 8000) -> str:
    """Cap a tool result so large outputs don't blow the context window."""
    if not text or len(text) <= max_chars:
        return text
    head = text[: max_chars // 2]
    tail = text[-max_chars // 2:]
    omitted = len(text) - max_chars
    return f"{head}\n\n... [truncated {omitted} chars] ...\n\n{tail}"


# ── Event types ───────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class TextChunk:
    """An incremental token slice from the assistant stream."""
    text: str
    round_index: int


@dataclass(frozen=True)
class ToolCallRequested:
    """The model has asked us to invoke a tool; about to execute."""
    call_id: str
    name: str
    arguments: Dict[str, Any]
    round_index: int


@dataclass(frozen=True)
class ToolCallResult:
    """A tool finished. The result has already been appended to messages as a
    'tool' role entry by the engine."""
    call_id: str
    name: str
    arguments: Dict[str, Any]
    result: str
    duration_ms: int
    round_index: int
    error: Optional[str] = None


@dataclass(frozen=True)
class RoundCompleted:
    """One stream finished. If had_tool_calls another round will follow."""
    round_index: int
    assistant_text: str
    had_tool_calls: bool


@dataclass(frozen=True)
class Done:
    """The turn is complete; no further events will follow."""
    final_text: str


@dataclass(frozen=True)
class Usage:
    """Token usage for one model call (round). prompt_tokens is the context the
    model read this round; completion_tokens is what it generated."""
    prompt_tokens: int
    completion_tokens: int
    round_index: int


@dataclass(frozen=True)
class Error:
    """A streaming or tool error.

    fatal=True   → engine stops; no Done will follow.
    fatal=False  → informational; the engine recovers (e.g. retried without
                   tools when the model rejects the tools field).
    """
    message: str
    fatal: bool = True
    retry_without_tools: bool = False


ChatEvent = Union[TextChunk, ToolCallRequested, ToolCallResult,
                  RoundCompleted, Usage, Done, Error]


# ── Session setup / teardown ──────────────────────────────────────────────────

def start_session(
    model_name: str,
    initial_messages: Optional[List[Dict[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    """
    Build (or rebuild) the messages list with a fresh system prompt drawn from
    current memory. If `initial_messages` already contains a system message it
    is replaced — resumed sessions always pick up the current memory state.

    Also strips `tool_calls` from any assistant messages so that a freshly
    downloaded model that doesn't support tools doesn't get a 400 on the
    first turn.
    """
    messages: List[Dict[str, Any]] = []
    for m in (initial_messages or []):
        clean = {k: v for k, v in m.items() if k != "tool_calls"}
        messages.append(clean)

    sys_prompt = build_system_prompt()
    if sys_prompt:
        if messages and messages[0].get("role") == "system":
            messages[0]["content"] = sys_prompt
        else:
            messages.insert(0, {"role": "system", "content": sys_prompt})
    return messages


def finalize_session(
    model_name: str,
    messages: List[Dict[str, Any]],
    temperature: float,
    start_time: datetime,
    backend: str = "ollama",
    stream_model: str = "",
) -> Optional[str]:
    """Persist the session if any user message exists. Returns saved path or None."""
    if any(m.get("role") == "user" for m in messages):
        path = save_session(
            model_name, messages, temperature, start_time,
            backend=backend, stream_model=stream_model,
        )
        return path or None
    return None


# ── Chat turn engine ──────────────────────────────────────────────────────────

def run_chat_turn(
    model_name: str,
    messages: List[Dict[str, Any]],
    *,
    temperature: float = 0.7,
    context_length: Optional[int] = None,
    tools_enabled: bool = True,
    max_tool_rounds: int = 25,
    stream_fn=None,
    approve_fn=None,
    tools_schema=None,
) -> Iterator[ChatEvent]:
    """
    Drive one assistant turn — initial text plus any subsequent tool rounds —
    for an already-appended user message. Mutates `messages` in place,
    appending assistant text and tool results as rounds complete.

    Always terminates with either Done or a fatal Error event.

    stream_fn: callable matching ollama_client.chat_stream signature.
    Defaults to ollama_client.chat_stream when None.

    approve_fn: optional callable(tool_name, args) -> bool, consulted before
    executing each tool. Returning False denies the call (the model is told).
    Used by agent Plan mode for interactive approval. Default = allow all.

    tools_schema: optional explicit tool schema. When provided (agent mode), the
    full set is always offered (the chat `wants_tools` intent gate is skipped).
    """
    # Resolve backend lazily — only imports ollama_client when needed
    if stream_fn is None:
        from .ollama_client import chat_stream as _sf
    else:
        _sf = stream_fn

    active_schema = tools_schema if tools_schema is not None else TOOLS_SCHEMA
    if tools_schema is not None:
        # Agent mode: tools are always available (no intent gate).
        tools_active = tools_enabled
    else:
        # Chat: only offer tools when the latest user message shows tool intent.
        tools_active = tools_enabled and wants_tools(messages)
    final_text = ""

    for round_index in range(max_tool_rounds):
        full_text = ""
        pending_tool_calls: List[Dict[str, Any]] = []

        prompt_tokens = 0
        completion_tokens = 0

        # One round may need to retry once if the model rejects the tools field.
        for attempt in (1, 2):
            full_text = ""
            pending_tool_calls = []
            prompt_tokens = 0
            completion_tokens = 0
            stream_kwargs: Dict[str, Any] = {}
            if tools_active:
                stream_kwargs["tools"] = active_schema

            retry = False
            try:
                for chunk in _sf(
                    model_name, messages, temperature,
                    context_length=context_length, **stream_kwargs,
                ):
                    if "error" in chunk:
                        err_msg = str(chunk["error"])
                        _tool_unsupported = (
                            "does not support tools" in err_msg.lower()
                            or "does not support tool" in err_msg.lower()
                            or ("400" in err_msg and tools_active)
                        )
                        if _tool_unsupported and tools_active:
                            tools_active = False
                            retry = True
                            yield Error(
                                message="Model does not support tools — retrying without.",
                                fatal=False,
                                retry_without_tools=True,
                            )
                            break
                        yield Error(message=f"API error: {err_msg}", fatal=True)
                        return

                    msg = chunk.get("message", {}) or {}
                    piece = msg.get("content", "")
                    if piece:
                        full_text += piece
                        yield TextChunk(text=piece, round_index=round_index)
                    for tc in msg.get("tool_calls", []) or []:
                        pending_tool_calls.append(tc)
                    # Token usage — Ollama (top-level eval counts) or API ("usage").
                    if "prompt_eval_count" in chunk or "eval_count" in chunk:
                        prompt_tokens = chunk.get("prompt_eval_count") or prompt_tokens
                        completion_tokens = chunk.get("eval_count") or completion_tokens
                    usage = chunk.get("usage")
                    if usage:
                        prompt_tokens = usage.get("prompt_tokens") or prompt_tokens
                        completion_tokens = usage.get("completion_tokens") or completion_tokens
            except Exception as exc:
                exc_str = str(exc).lower()
                _tool_exc = (
                    "does not support tools" in exc_str
                    or ("400" in exc_str and tools_active)
                )
                if _tool_exc and tools_active:
                    tools_active = False
                    retry = True
                    yield Error(
                        message="Model does not support tools — retrying without.",
                        fatal=False,
                        retry_without_tools=True,
                    )
                else:
                    yield Error(message=f"Unexpected error: {exc}", fatal=True)
                    return

            if not retry:
                break

        # Report this round's token usage (if the backend provided it).
        if prompt_tokens or completion_tokens:
            yield Usage(
                prompt_tokens=int(prompt_tokens),
                completion_tokens=int(completion_tokens),
                round_index=round_index,
            )

        # ── No tool calls → final text, end turn ──────────────────────────
        if not pending_tool_calls:
            messages.append({"role": "assistant", "content": full_text})
            final_text = full_text
            yield RoundCompleted(
                round_index=round_index,
                assistant_text=full_text,
                had_tool_calls=False,
            )
            yield Done(final_text=final_text)
            return

        # ── Append assistant message carrying tool_calls metadata ─────────
        messages.append({
            "role": "assistant",
            "content": full_text,
            "tool_calls": pending_tool_calls,
        })
        final_text = full_text
        yield RoundCompleted(
            round_index=round_index,
            assistant_text=full_text,
            had_tool_calls=True,
        )

        # ── Execute each tool; append result and emit events ──────────────
        for tc in pending_tool_calls:
            fn = tc.get("function", {}) or {}
            name = fn.get("name", "")
            raw_args = fn.get("arguments", {})
            if isinstance(raw_args, str):
                try:
                    args = json.loads(raw_args)
                except Exception:
                    args = {}
            elif isinstance(raw_args, dict):
                args = raw_args
            else:
                args = {}

            call_id = tc.get("id") or f"call_{uuid.uuid4().hex[:8]}"

            yield ToolCallRequested(
                call_id=call_id, name=name, arguments=args,
                round_index=round_index,
            )

            t0 = time.monotonic()
            if approve_fn is not None and not approve_fn(name, args):
                result_text = "[Denied by user] The user declined this action."
                error = None
            else:
                try:
                    result_text = _truncate(run_tool(name, **args))
                    error = None
                except Exception as exc:
                    result_text = f"[Tool Error] {exc}"
                    error = str(exc)
            duration_ms = int((time.monotonic() - t0) * 1000)

            messages.append({"role": "tool", "content": result_text})

            yield ToolCallResult(
                call_id=call_id, name=name, arguments=args,
                result=result_text, duration_ms=duration_ms,
                round_index=round_index, error=error,
            )

        # Loop: let the model respond again with the tool output in context.

    # Exceeded max rounds.
    yield Error(
        message=f"Tool-call loop limit reached ({max_tool_rounds} rounds).",
        fatal=True,
    )
