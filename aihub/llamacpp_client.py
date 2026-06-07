"""
AIHub — llama.cpp server client (v0.2.0).

Connects to an *already-running* llama-server via its OpenAI-compatible REST
API. AIHub does NOT launch or manage the process.

    Health:   GET  /health
    Models:   GET  /v1/models
    Chat:     POST /v1/chat/completions  (SSE streaming or non-streaming)

Streaming chunks are normalised to match ollama_client.chat_stream() output
so chat.py run_chat_turn works with either backend unchanged.
"""
from __future__ import annotations

import json
from typing import Any, Dict, Generator, List, Optional

import requests

from .config import config


def _base() -> str:
    return config.llamacpp_url.rstrip("/")


# ── Status ────────────────────────────────────────────────────────────────────

def is_llamacpp_running() -> bool:
    """Return True if llama-server /health responds with status ok."""
    try:
        r = requests.get(f"{_base()}/health", timeout=2)
        return r.status_code == 200 and r.json().get("status") == "ok"
    except Exception:
        return False


def get_loaded_model() -> str:
    """Return the id of the currently loaded model, or '' on any error.
    llama-server allows exactly one model at a time."""
    try:
        r = requests.get(f"{_base()}/v1/models", timeout=3)
        r.raise_for_status()
        data = r.json().get("data") or []
        return data[0]["id"] if data else ""
    except Exception:
        return ""


# ── Chat streaming ────────────────────────────────────────────────────────────

def chat_stream(
    model_name: str,
    messages: List[Dict[str, Any]],
    temperature: float = 0.7,
    tools: Optional[List[Dict[str, Any]]] = None,
    context_length: Optional[int] = None,
) -> Generator[Dict[str, Any], None, None]:
    """
    POST /v1/chat/completions with stream=True.

    Parses SSE lines and yields dicts in the *same shape* as
    ollama_client.chat_stream() so run_chat_turn needs no branch logic:

        {"message": {"content": "token"}, "done": False}
        {"message": {"content": ""}, "done": True}
        {"error": "..."} on any failure

    SSE format from llama-server:
        data: {"choices": [{"delta": {"content": "hi"}, "finish_reason": null}]}
        ...
        data: [DONE]
    """
    url = f"{_base()}/v1/chat/completions"
    payload: Dict[str, Any] = {
        "model":       model_name,
        "messages":    messages,
        "stream":      True,
        "temperature": temperature,
    }
    if context_length:
        payload["max_tokens"] = context_length  # closest OpenAI equivalent to num_ctx
    if tools:
        payload["tools"] = tools
        payload["tool_choice"] = "auto"

    try:
        resp = requests.post(url, json=payload, stream=True, timeout=120)
        if not resp.ok:
            try:
                body = resp.json()
                err = body.get("error") or {}
                reason = err.get("message") if isinstance(err, dict) else str(err)
                reason = reason or body.get("message") or resp.text
            except Exception:
                reason = resp.text or resp.reason
            yield {"error": f"{resp.status_code}: {reason}"}
            return

        # Accumulator for tool-call argument fragments (keyed by tool-call index)
        _tc_bufs: Dict[int, Dict[str, Any]] = {}

        for raw_line in resp.iter_lines():
            if not raw_line:
                continue
            line = raw_line.decode("utf-8", errors="replace") if isinstance(raw_line, bytes) else raw_line
            if not line.startswith("data:"):
                continue
            payload_str = line[5:].strip()

            if payload_str == "[DONE]":
                # Flush any buffered tool calls
                if _tc_bufs:
                    normed = _flush_tc_bufs(_tc_bufs)
                    yield {"message": {"content": "", "tool_calls": normed}, "done": False}
                    _tc_bufs.clear()
                yield {"message": {"content": ""}, "done": True}
                return

            try:
                sse = json.loads(payload_str)
            except json.JSONDecodeError:
                continue

            choices = sse.get("choices") or []
            if not choices:
                continue

            choice = choices[0]
            delta = choice.get("delta") or {}
            finish_reason = choice.get("finish_reason")

            content = delta.get("content") or ""
            tc_list = delta.get("tool_calls") or []

            # Accumulate tool-call argument fragments by index
            for tc in tc_list:
                idx = tc.get("index", 0)
                if idx not in _tc_bufs:
                    fn = tc.get("function") or {}
                    _tc_bufs[idx] = {
                        "id":       tc.get("id", ""),
                        "name":     fn.get("name", ""),
                        "args_buf": fn.get("arguments", ""),
                    }
                else:
                    fn = tc.get("function") or {}
                    _tc_bufs[idx]["args_buf"] += fn.get("arguments", "")
                    if tc.get("id"):
                        _tc_bufs[idx]["id"] = tc["id"]
                    if fn.get("name"):
                        _tc_bufs[idx]["name"] = fn["name"]

            if finish_reason == "tool_calls" and _tc_bufs:
                normed = _flush_tc_bufs(_tc_bufs)
                _tc_bufs.clear()
                yield {"message": {"content": content, "tool_calls": normed}, "done": False}
            elif content:
                yield {"message": {"content": content}, "done": False}

    except Exception as exc:
        yield {"error": str(exc)}


def _flush_tc_bufs(bufs: Dict[int, Dict]) -> List[Dict[str, Any]]:
    """Convert accumulated tool-call fragments to Ollama-normalised shape."""
    result = []
    for idx in sorted(bufs):
        b = bufs[idx]
        raw_args = b["args_buf"]
        try:
            args = json.loads(raw_args) if raw_args else {}
        except Exception:
            args = {}
        result.append({
            "id":       b["id"],
            "function": {"name": b["name"], "arguments": args},
        })
    return result


# ── Non-streaming ─────────────────────────────────────────────────────────────

def chat_sync(
    model_name: str,
    messages: List[Dict[str, Any]],
    temperature: float = 0.7,
    context_length: Optional[int] = None,
) -> str:
    """Non-streaming POST /v1/chat/completions. Returns full response string."""
    url = f"{_base()}/v1/chat/completions"
    payload: Dict[str, Any] = {
        "model":       model_name,
        "messages":    messages,
        "stream":      False,
        "temperature": temperature,
    }
    if context_length:
        payload["max_tokens"] = context_length
    try:
        r = requests.post(url, json=payload, timeout=120)
        r.raise_for_status()
        choices = r.json().get("choices") or [{}]
        return choices[0].get("message", {}).get("content", "")
    except Exception:
        return "Error: Could not generate a response."
