"""
AIHub — OpenAI chat-completions wire format.

Shared by the two OpenAI-compatible backends, llama.cpp (llama-server) and the
OpenAI API: converting AIHub's stored messages into the request shape, and
turning the SSE response stream back into the Ollama-shaped chunks that
chat.run_chat_turn consumes.

Stored messages use Ollama's shape — tool-call arguments are dicts, results
are {"role": "tool", "tool_call_id", "tool_name"}. OpenAI-compatible servers
require arguments as a JSON *string* and every tool result to reference the
id of a preceding call (llama-server answers 400 otherwise).
"""
from __future__ import annotations

import json
from typing import Any, Dict, Iterator, List


def image_data(m: Dict[str, Any]) -> List[Dict[str, str]]:
    from .attachments import image_data as _imgs
    return _imgs(m)


def to_openai_messages(messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Convert stored messages to OpenAI chat-completions messages.

    Sessions saved before tool calls carried ids get positional ids: each
    call is paired with the next tool result, in order.
    """
    out: List[Dict[str, Any]] = []
    unanswered: List[str] = []   # ids of calls awaiting a result, in order
    for i, m in enumerate(messages):
        role = m.get("role")
        content = m.get("content") or ""
        if role == "user" and image_data(m):
            # Vision: text + data-URL images as content parts.
            parts: List[Dict[str, Any]] = [{"type": "text", "text": content}] if content else []
            parts += [{"type": "image_url", "image_url": {"url": f"data:{i['mime']};base64,{i['data']}"}}
                      for i in image_data(m)]
            out.append({"role": "user", "content": parts})
        elif role in ("system", "user"):
            out.append({"role": role, "content": content})
        elif role == "assistant":
            msg: Dict[str, Any] = {"role": "assistant", "content": content}
            calls = []
            for j, tc in enumerate(m.get("tool_calls") or []):
                fn = tc.get("function") or {}
                args = fn.get("arguments", {})
                call_id = tc.get("id") or f"call_{i}_{j}"
                calls.append({
                    "id": call_id,
                    "type": "function",
                    "function": {
                        "name": fn.get("name", ""),
                        "arguments": args if isinstance(args, str) else json.dumps(args),
                    },
                })
                unanswered.append(call_id)
            if calls:
                msg["tool_calls"] = calls
            out.append(msg)
        elif role == "tool":
            call_id = m.get("tool_call_id")
            if call_id in unanswered:
                unanswered.remove(call_id)
            elif unanswered:
                call_id = unanswered.pop(0)
            else:
                # A result with no call to answer (hand-edited history):
                # keep the text, as context, rather than send an invalid turn.
                out.append({"role": "user", "content": f"[tool result] {content}"})
                continue
            out.append({"role": "tool", "tool_call_id": call_id, "content": content})
    return out


def _flush_tool_calls(bufs: Dict[int, Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Accumulated tool-call fragments → Ollama-shaped calls (dict arguments)."""
    result = []
    for idx in sorted(bufs):
        b = bufs[idx]
        try:
            args = json.loads(b["args"]) if b["args"] else {}
        except Exception:
            args = {}
        result.append({"id": b["id"], "function": {"name": b["name"], "arguments": args}})
    bufs.clear()
    return result


def iter_sse_chunks(lines: Iterator[Any]) -> Iterator[Dict[str, Any]]:
    """Parse a chat-completions SSE stream (`resp.iter_lines()`) into
    Ollama-shaped chunks: text deltas, tool calls (argument fragments are
    accumulated per index and emitted whole), and token usage."""
    bufs: Dict[int, Dict[str, Any]] = {}
    for raw in lines:
        if not raw:
            continue
        line = raw.decode("utf-8", errors="replace") if isinstance(raw, bytes) else raw
        if not line.startswith("data:"):
            continue
        data = line[5:].strip()
        if data == "[DONE]":
            break
        try:
            obj = json.loads(data)
        except json.JSONDecodeError:
            continue

        usage = obj.get("usage")
        if usage:
            yield {"message": {"content": ""}, "done": False, "usage": {
                "prompt_tokens": usage.get("prompt_tokens") or 0,
                "completion_tokens": usage.get("completion_tokens") or 0,
            }}

        choices = obj.get("choices") or []
        if not choices:
            continue
        delta = choices[0].get("delta") or {}
        # llama-server / DeepSeek-style reasoning streams separately.
        thought = delta.get("reasoning_content") or delta.get("reasoning") or ""
        if thought:
            yield {"message": {"content": "", "thinking": thought}, "done": False}
        content = delta.get("content") or ""
        if content:
            yield {"message": {"content": content}, "done": False}
        for tc in delta.get("tool_calls") or []:
            b = bufs.setdefault(tc.get("index", 0), {"id": "", "name": "", "args": ""})
            fn = tc.get("function") or {}
            if tc.get("id"):
                b["id"] = tc["id"]
            if fn.get("name"):
                b["name"] = fn["name"]
            b["args"] += fn.get("arguments") or ""
        if choices[0].get("finish_reason") and bufs:
            yield {"message": {"content": "", "tool_calls": _flush_tool_calls(bufs)}, "done": False}

    # Stream ended ([DONE] or connection close) with calls still buffered.
    if bufs:
        yield {"message": {"content": "", "tool_calls": _flush_tool_calls(bufs)}, "done": False}
    yield {"message": {"content": ""}, "done": True}
