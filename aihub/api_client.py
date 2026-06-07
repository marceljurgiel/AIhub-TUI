"""
AIHub — Cloud API client (v0.2.0).

Unified streaming client for OpenAI, Anthropic, and Google Gemini. Each
provider's stream is normalised to the same chunk shape produced by
ollama_client.chat_stream(), so chat.run_chat_turn() works unchanged:

    {"message": {"content": "token"}, "done": False}
    {"message": {"content": ""}, "done": True}
    {"error": "..."} on any failure

The `model_name` passed in is the api:// URL form: "api://<provider>/<model>".
Anthropic uses the official `anthropic` SDK (its API is not OpenAI-compatible).
OpenAI uses its OpenAI-compatible SSE endpoint (same shape as llama.cpp).
Google uses the Gemini streamGenerateContent endpoint.
"""
from __future__ import annotations

import json
from typing import Any, Dict, Generator, List, Optional, Tuple

import requests

from .config import config


# ── URL parsing ───────────────────────────────────────────────────────────────

def parse_api_url(model_name: str) -> Tuple[str, str]:
    """Split 'api://<provider>/<model>' → (provider, model). Tolerant of a bare
    model id if it isn't prefixed."""
    if model_name.startswith("api://"):
        rest = model_name[len("api://"):]
        provider, _, model = rest.partition("/")
        return provider, model
    return "", model_name


def chat_stream(
    model_name: str,
    messages: List[Dict[str, Any]],
    temperature: float = 0.7,
    tools: Optional[List[Dict[str, Any]]] = None,
    context_length: Optional[int] = None,
) -> Generator[Dict[str, Any], None, None]:
    """Route to the right provider; yield Ollama-shaped chunks."""
    provider, model = parse_api_url(model_name)
    try:
        if provider == "anthropic":
            yield from _anthropic_stream(model, messages, temperature)
        elif provider == "openai":
            yield from _openai_stream(model, messages, temperature)
        elif provider == "google":
            yield from _google_stream(model, messages, temperature)
        else:
            yield {"error": f"Unknown API provider: {provider!r}"}
    except Exception as exc:
        yield {"error": str(exc)}


# ── Message conversion helpers ────────────────────────────────────────────────

def _split_system(messages: List[Dict[str, Any]]) -> Tuple[str, List[Dict[str, Any]]]:
    """Pull out system text; return (system_text, non_system_messages)."""
    system_parts: List[str] = []
    rest: List[Dict[str, Any]] = []
    for m in messages:
        if m.get("role") == "system":
            if m.get("content"):
                system_parts.append(m["content"])
        else:
            rest.append(m)
    return "\n\n".join(system_parts), rest


# ── Anthropic (official SDK) ──────────────────────────────────────────────────

def _anthropic_stream(
    model: str,
    messages: List[Dict[str, Any]],
    temperature: float,
) -> Generator[Dict[str, Any], None, None]:
    import anthropic

    key = config.anthropic_api_key.strip()
    if not key:
        yield {"error": "Anthropic API key not set. Add it in Settings (Ctrl+,)."}
        return

    system_text, convo = _split_system(messages)

    # Anthropic messages: user/assistant only, content as plain strings.
    # Map any 'tool' role to a user message carrying the tool output text.
    api_messages: List[Dict[str, Any]] = []
    for m in convo:
        role = m.get("role")
        content = m.get("content", "")
        if role == "tool":
            api_messages.append({"role": "user", "content": f"[tool result] {content}"})
        elif role in ("user", "assistant") and content:
            api_messages.append({"role": role, "content": content})
    if not api_messages:
        api_messages = [{"role": "user", "content": "Hello"}]

    client = anthropic.Anthropic(api_key=key)

    # Streaming, so no HTTP-timeout risk — give the model room so long answers
    # (e.g. code) don't truncate mid-thought.
    kwargs: Dict[str, Any] = {
        "model":      model,
        "max_tokens": 16000,
        "messages":   api_messages,
    }
    if system_text:
        kwargs["system"] = system_text
    if not model.startswith("claude-opus-4-8") and not model.startswith("claude-opus-4-7"):
        kwargs["temperature"] = max(0.0, min(1.0, temperature))

    try:
        with client.messages.stream(**kwargs) as stream:
            for text in stream.text_stream:
                if text:
                    yield {"message": {"content": text}, "done": False}
        yield {"message": {"content": ""}, "done": True}
    except anthropic.AuthenticationError:
        yield {"error": "Invalid Anthropic API key."}
    except anthropic.RateLimitError:
        yield {"error": "Anthropic rate limit reached. Try again shortly."}
    except anthropic.APIStatusError as exc:
        yield {"error": f"Anthropic API error {exc.status_code}: {exc.message}"}
    except Exception as exc:
        yield {"error": f"Anthropic error: {exc}"}


# ── OpenAI (OpenAI-compatible SSE) ────────────────────────────────────────────

def _openai_stream(
    model: str,
    messages: List[Dict[str, Any]],
    temperature: float,
) -> Generator[Dict[str, Any], None, None]:
    key = config.openai_api_key.strip()
    if not key:
        yield {"error": "OpenAI API key not set. Add it in Settings (Ctrl+,)."}
        return

    # OpenAI accepts the messages list as-is (system/user/assistant). Map our
    # 'tool' role to a user message for simplicity.
    api_messages = []
    for m in messages:
        role = m.get("role")
        content = m.get("content", "")
        if role == "tool":
            api_messages.append({"role": "user", "content": f"[tool result] {content}"})
        elif role in ("system", "user", "assistant") and content:
            api_messages.append({"role": role, "content": content})

    payload: Dict[str, Any] = {
        "model":    model,
        "messages": api_messages,
        "stream":   True,
    }
    # o1 models reject temperature; gpt-4o accepts it.
    if not model.startswith("o1"):
        payload["temperature"] = temperature

    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type":  "application/json",
    }
    try:
        resp = requests.post(
            "https://api.openai.com/v1/chat/completions",
            json=payload, headers=headers, stream=True, timeout=120,
        )
        if not resp.ok:
            try:
                reason = resp.json().get("error", {}).get("message", resp.text)
            except Exception:
                reason = resp.text
            yield {"error": f"OpenAI {resp.status_code}: {reason}"}
            return
        for raw in resp.iter_lines():
            if not raw:
                continue
            line = raw.decode("utf-8", errors="replace") if isinstance(raw, bytes) else raw
            if not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if data == "[DONE]":
                yield {"message": {"content": ""}, "done": True}
                return
            try:
                obj = json.loads(data)
            except json.JSONDecodeError:
                continue
            delta = (obj.get("choices") or [{}])[0].get("delta", {})
            piece = delta.get("content") or ""
            if piece:
                yield {"message": {"content": piece}, "done": False}
        yield {"message": {"content": ""}, "done": True}
    except Exception as exc:
        yield {"error": f"OpenAI error: {exc}"}


# ── Google Gemini (streamGenerateContent) ─────────────────────────────────────

def _google_stream(
    model: str,
    messages: List[Dict[str, Any]],
    temperature: float,
) -> Generator[Dict[str, Any], None, None]:
    key = config.google_api_key.strip()
    if not key:
        yield {"error": "Google API key not set. Add it in Settings (Ctrl+,)."}
        return

    system_text, convo = _split_system(messages)

    # Gemini "contents": role is "user" or "model"; parts is a list of {text}.
    contents = []
    for m in convo:
        role = m.get("role")
        content = m.get("content", "")
        if not content:
            continue
        g_role = "model" if role == "assistant" else "user"
        if role == "tool":
            content = f"[tool result] {content}"
        contents.append({"role": g_role, "parts": [{"text": content}]})
    if not contents:
        contents = [{"role": "user", "parts": [{"text": "Hello"}]}]

    payload: Dict[str, Any] = {
        "contents": contents,
        "generationConfig": {"temperature": temperature},
    }
    if system_text:
        payload["systemInstruction"] = {"parts": [{"text": system_text}]}

    url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/"
        f"{model}:streamGenerateContent?alt=sse&key={key}"
    )
    try:
        resp = requests.post(
            url, json=payload,
            headers={"Content-Type": "application/json"},
            stream=True, timeout=120,
        )
        if not resp.ok:
            try:
                reason = resp.json().get("error", {}).get("message", resp.text)
            except Exception:
                reason = resp.text
            yield {"error": f"Google {resp.status_code}: {reason}"}
            return
        for raw in resp.iter_lines():
            if not raw:
                continue
            line = raw.decode("utf-8", errors="replace") if isinstance(raw, bytes) else raw
            if not line.startswith("data:"):
                continue
            data = line[5:].strip()
            try:
                obj = json.loads(data)
            except json.JSONDecodeError:
                continue
            candidates = obj.get("candidates") or []
            if not candidates:
                continue
            parts = candidates[0].get("content", {}).get("parts", [])
            for p in parts:
                piece = p.get("text") or ""
                if piece:
                    yield {"message": {"content": piece}, "done": False}
        yield {"message": {"content": ""}, "done": True}
    except Exception as exc:
        yield {"error": f"Google error: {exc}"}
