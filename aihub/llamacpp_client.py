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
from .openai_format import iter_sse_chunks, to_openai_messages


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
        "messages":    to_openai_messages(messages),
        "stream":      True,
        "temperature": temperature,
    }
    # context_length is not sent: llama-server's context is fixed by its
    # --ctx-size at launch. (It used to go out as max_tokens, which caps the
    # *reply* length instead.)
    if tools:
        payload["tools"] = tools
        payload["tool_choice"] = "auto"

    resp = None
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
        yield from iter_sse_chunks(resp.iter_lines())
    except Exception as exc:
        yield {"error": str(exc)}
    finally:
        # Also runs on early generator close (cancel) — frees the server slot.
        if resp is not None:
            resp.close()


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
        "messages":    to_openai_messages(messages),
        "stream":      False,
        "temperature": temperature,
    }
    # context_length intentionally unused — see chat_stream.
    try:
        r = requests.post(url, json=payload, timeout=120)
        r.raise_for_status()
        choices = r.json().get("choices") or [{}]
        return choices[0].get("message", {}).get("content", "")
    except Exception:
        return "Error: Could not generate a response."
