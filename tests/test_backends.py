"""Backend wire formats: tool-call ids, OpenAI-compatible conversion/parsing,
llama.cpp and OpenAI request payloads, error handling, agent gating."""
from __future__ import annotations

import asyncio
import json

import pytest

from aihub import api_client, llamacpp_client
from aihub.agent import agent_capable
from aihub.chat import Done, Error, run_chat_turn
from aihub.openai_format import iter_sse_chunks, to_openai_messages

from .conftest import SCHEMA, FakeBackend, text, tool_call


# ── Engine: stored tool calls are linked by id ────────────────────────────────

def test_engine_stores_ids_linking_calls_to_results(tool_runs):
    backend = FakeBackend([
        [tool_call({"name": "read_file", "args": {"path": "a"}},
                   {"name": "read_file", "args": {"path": "b"}})],
        [text("done")],
    ])
    messages = [{"role": "user", "content": "hi"}]
    list(run_chat_turn("m", messages, stream_fn=backend, tools_schema=SCHEMA))

    call_msg = messages[1]
    ids = [tc["id"] for tc in call_msg["tool_calls"]]
    assert all(ids) and len(set(ids)) == 2
    assert all(tc["type"] == "function" for tc in call_msg["tool_calls"])
    assert [m["tool_call_id"] for m in messages[2:4]] == ids
    assert [m["tool_name"] for m in messages[2:4]] == ["read_file", "read_file"]


def test_engine_keeps_backend_supplied_ids(tool_runs):
    chunk = {"message": {"content": "", "tool_calls": [
        {"id": "call_abc", "function": {"name": "read_file", "arguments": '{"path": "x"}'}}]}}
    messages = [{"role": "user", "content": "hi"}]
    list(run_chat_turn("m", messages, stream_fn=FakeBackend([[chunk], [text("ok")]]),
                       tools_schema=SCHEMA))

    assert messages[1]["tool_calls"][0]["id"] == "call_abc"
    assert messages[1]["tool_calls"][0]["function"]["arguments"] == {"path": "x"}
    assert messages[2]["tool_call_id"] == "call_abc"


# ── Engine: which errors mean "no tools" ──────────────────────────────────────

def _first_round_error(msg):
    backend = FakeBackend([[{"error": msg}], [text("plain answer")]])
    events = list(run_chat_turn("m", [{"role": "user", "content": "hi"}],
                                stream_fn=backend, tools_schema=SCHEMA))
    return events, backend


@pytest.mark.parametrize("msg", [
    "400: registry.ollama.ai/library/gemma:2b does not support tools",
    "500: tools param requires --jinja flag",
])
def test_explicit_no_tools_errors_retry_without_tools(msg):
    events, backend = _first_round_error(msg)
    assert backend.calls == 2
    assert events[-1] == Done(final_text="plain answer")


def test_a_plain_400_is_reported_not_retried():
    msg = "400: json: cannot unmarshal object into Go struct field .messages.tool_calls.function.arguments of type string"
    events, backend = _first_round_error(msg)
    assert backend.calls == 1
    errors = [e for e in events if isinstance(e, Error)]
    assert len(errors) == 1 and errors[0].fatal and "cannot unmarshal" in errors[0].message


# ── OpenAI message conversion ─────────────────────────────────────────────────

def test_to_openai_messages_stringifies_arguments_and_links_ids():
    out = to_openai_messages([
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "", "tool_calls": [
            {"id": "c1", "type": "function",
             "function": {"name": "read_file", "arguments": {"path": "a"}}}]},
        {"role": "tool", "content": "A", "tool_call_id": "c1", "tool_name": "read_file"},
        {"role": "assistant", "content": "done"},
    ])
    assert out[2]["tool_calls"] == [{"id": "c1", "type": "function", "function": {
        "name": "read_file", "arguments": json.dumps({"path": "a"})}}]
    assert out[3] == {"role": "tool", "tool_call_id": "c1", "content": "A"}
    assert "tool_name" not in out[3]


def test_to_openai_messages_pairs_old_sessions_without_ids():
    # Sessions saved before ids existed: calls and results pair up in order.
    out = to_openai_messages([
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "", "tool_calls": [
            {"function": {"name": "read_file", "arguments": {"path": "a"}}},
            {"function": {"name": "read_file", "arguments": {"path": "b"}}}]},
        {"role": "tool", "content": "A"},
        {"role": "tool", "content": "B"},
    ])
    ids = [tc["id"] for tc in out[1]["tool_calls"]]
    assert len(set(ids)) == 2
    assert [m["tool_call_id"] for m in out[2:]] == ids


def test_to_openai_messages_orphan_tool_result_becomes_context():
    out = to_openai_messages([{"role": "user", "content": "hi"},
                              {"role": "tool", "content": "stray"}])
    assert out[1] == {"role": "user", "content": "[tool result] stray"}


# ── OpenAI SSE parsing ────────────────────────────────────────────────────────

def _sse(*objs, done=True):
    lines = [f"data: {json.dumps(o)}".encode() for o in objs]
    if done:
        lines.append(b"data: [DONE]")
    return iter(lines)


def test_sse_accumulates_fragmented_tool_calls():
    chunks = list(iter_sse_chunks(_sse(
        {"choices": [{"delta": {"content": "Let me look."}}]},
        {"choices": [{"delta": {"tool_calls": [
            {"index": 0, "id": "c1", "function": {"name": "read_file", "arguments": '{"pa'}}]}}]},
        {"choices": [{"delta": {"tool_calls": [
            {"index": 0, "function": {"arguments": 'th": "a"}'}},
            {"index": 1, "id": "c2", "function": {"name": "list_files", "arguments": "{}"}}]}}]},
        {"choices": [{"delta": {}, "finish_reason": "tool_calls"}]},
        {"choices": [], "usage": {"prompt_tokens": 12, "completion_tokens": 5}},
    )))
    assert chunks[0]["message"]["content"] == "Let me look."
    calls = next(c["message"]["tool_calls"] for c in chunks if c["message"].get("tool_calls"))
    assert calls == [
        {"id": "c1", "function": {"name": "read_file", "arguments": {"path": "a"}}},
        {"id": "c2", "function": {"name": "list_files", "arguments": {}}},
    ]
    assert any(c.get("usage") == {"prompt_tokens": 12, "completion_tokens": 5} for c in chunks)
    assert chunks[-1]["done"] is True


def test_sse_flushes_calls_when_stream_ends_without_done():
    chunks = list(iter_sse_chunks(_sse(
        {"choices": [{"delta": {"tool_calls": [
            {"index": 0, "id": "c1", "function": {"name": "read_file", "arguments": "{}"}}]}}]},
        done=False)))
    assert any(c["message"].get("tool_calls") for c in chunks)


# ── Request payloads ──────────────────────────────────────────────────────────

class _FakeResp:
    ok = True
    status_code = 200

    def __init__(self, lines):
        self._lines = lines
        self.closed = False

    def iter_lines(self):
        return iter(self._lines)

    def close(self):
        self.closed = True


@pytest.fixture
def captured_post(monkeypatch):
    seen = {}

    def fake_post(url, json=None, **kw):
        seen["url"], seen["payload"], seen["headers"] = url, json, kw.get("headers")
        seen["resp"] = _FakeResp([b'data: {"choices":[{"delta":{"content":"ok"}}]}', b"data: [DONE]"])
        return seen["resp"]

    monkeypatch.setattr("requests.post", fake_post)
    return seen


HISTORY = [
    {"role": "user", "content": "hi"},
    {"role": "assistant", "content": "", "tool_calls": [
        {"id": "c1", "type": "function", "function": {"name": "read_file", "arguments": {"path": "a"}}}]},
    {"role": "tool", "content": "A", "tool_call_id": "c1", "tool_name": "read_file"},
]


def test_llamacpp_payload_is_openai_shaped_without_max_tokens(captured_post):
    list(llamacpp_client.chat_stream("m", HISTORY, 0.5, tools=SCHEMA, context_length=8192))
    p = captured_post["payload"]
    assert "max_tokens" not in p
    assert p["messages"] == to_openai_messages(HISTORY)
    assert p["tools"] == SCHEMA and p["tool_choice"] == "auto"
    assert captured_post["resp"].closed


def test_openai_client_sends_tools_and_converted_history(captured_post, monkeypatch):
    monkeypatch.setattr(api_client.config, "openai_api_key", "sk-test")
    chunks = list(api_client.chat_stream("api://openai/gpt-4o", HISTORY, 0.5, tools=SCHEMA))
    p = captured_post["payload"]
    assert captured_post["url"] == f"{api_client.OPENAI_BASE_URL}/chat/completions"
    assert p["tools"] == SCHEMA
    assert p["messages"] == to_openai_messages(HISTORY)
    assert p["stream_options"] == {"include_usage": True}
    assert chunks[0]["message"]["content"] == "ok"


# ── Agent gating ──────────────────────────────────────────────────────────────

@pytest.mark.parametrize("model,ok", [
    ("api://openai/gpt-4o", True),
    ("OpenAI · GPT-4o", True),
    ("api://anthropic/claude-opus-4-8", False),
    ("Anthropic · Claude Opus 4.8", False),
    ("api://google/gemini-2.0-flash", False),
])
def test_agent_mode_only_for_providers_with_tool_calling(model, ok):
    assert agent_capable(model, "api")[0] is ok


# ── Reasoning ("thinking") streams ────────────────────────────────────────────

def test_engine_emits_thinking_but_keeps_it_out_of_history():
    from aihub.chat import ThinkingChunk
    backend = FakeBackend([[
        {"message": {"content": "", "thinking": "Let me "}},
        {"message": {"content": "", "thinking": "compute."}},
        text("391"),
    ]])
    messages = [{"role": "user", "content": "17*23?"}]
    events = list(run_chat_turn("m", messages, stream_fn=backend))
    assert [e.text for e in events if isinstance(e, ThinkingChunk)] == ["Let me ", "compute."]
    assert messages[-1] == {"role": "assistant", "content": "391"}


def test_sse_reasoning_content_becomes_thinking():
    chunks = list(iter_sse_chunks(_sse(
        {"choices": [{"delta": {"reasoning_content": "hmm"}}]},
        {"choices": [{"delta": {"content": "ok"}}]},
    )))
    assert chunks[0]["message"] == {"content": "", "thinking": "hmm"}
    assert chunks[1]["message"]["content"] == "ok"


def test_bridge_forwards_thinking(monkeypatch):
    from aihub import bridge
    from aihub.chat import ThinkingChunk
    out = []
    monkeypatch.setattr(bridge, "_emit", lambda rid, ev, data=None: out.append((ev, data)))
    bridge._emit_chat_event(1, ThinkingChunk("hmm", 0))
    assert out == [("thinking", {"text": "hmm", "round": 0})]
