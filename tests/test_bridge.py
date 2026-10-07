"""bridge._stream_chat_turn: chat.cancel stops the turn cleanly."""
from __future__ import annotations

import pytest

from aihub import bridge

from .conftest import FakeBackend, text, tool_call


@pytest.fixture
def wire(monkeypatch):
    """Capture everything the bridge would write to stdout."""
    out = {"events": [], "done": None}

    def fake_emit(req_id, event, data=None):
        out["events"].append((event, data))
        hook = out.get("on_emit")
        if hook:
            hook(req_id, event, data)

    monkeypatch.setattr(bridge, "_emit", fake_emit)
    monkeypatch.setattr(bridge, "_done",
                        lambda req_id, data=None: out.__setitem__("done", data))
    return out


def _turn(monkeypatch, backend, req_id=5, **params):
    monkeypatch.setattr(bridge, "_resolve_stream_fn", lambda m, b: backend)
    p = {"model": "m", "backend": "ollama", "tools_enabled": False,
         "messages": [{"role": "user", "content": "hi"}]}
    p.update(params)
    bridge._stream_chat_turn(req_id, p)


def _cancel(req_id):
    bridge._cancel_events[req_id].set()


def test_cancel_mid_stream_stops_reading_and_keeps_partial(monkeypatch, wire):
    backend = FakeBackend([[text("a"), text("b"), text("c"), text("d")]])

    def on_emit(req_id, event, data):
        if event == "text" and data["text"] == "a":
            _cancel(req_id)          # front-end sends chat.cancel

    wire["on_emit"] = on_emit
    _turn(monkeypatch, backend)

    assert [d["text"] for e, d in wire["events"] if e == "text"] == ["a"]
    assert backend.pulled == 2 and backend.closed == 1
    assert wire["done"]["cancelled"] is True
    assert wire["done"]["messages"][-1] == {"role": "assistant", "content": "a"}
    assert not bridge._cancel_events and not bridge._perm_queues


def test_cancel_between_tools_keeps_history_valid(monkeypatch, wire):
    runs = []

    def run_tool(name, **kwargs):
        runs.append(kwargs["path"])
        _cancel(5)
        return "ok"

    monkeypatch.setattr("aihub.chat.run_tool", run_tool)
    backend = FakeBackend([[tool_call(
        {"name": "read_file", "args": {"path": "a"}},
        {"name": "read_file", "args": {"path": "b"}},
    )]])
    _turn(monkeypatch, backend, agent=True, submode="build")

    assert runs == ["a"]
    msgs = wire["done"]["messages"]
    assert wire["done"]["cancelled"] is True
    assert [m["role"] for m in msgs[-3:]] == ["assistant", "tool", "tool"]
    assert msgs[-1]["content"].startswith("[Cancelled by user]")


def test_cancel_while_permission_pending_denies_and_stops(monkeypatch, wire):
    runs = []
    monkeypatch.setattr("aihub.chat.run_tool", lambda name, **kw: runs.append(name) or "ok")

    def on_emit(req_id, event, data):
        if event == "permission_request":
            # What the chat.cancel control message does.
            _cancel(req_id)
            bridge._perm_queues[req_id].put(False)

    wire["on_emit"] = on_emit
    backend = FakeBackend([[tool_call({"name": "run_terminal", "args": {"command": "ls"}})],
                           [text("never")]])
    _turn(monkeypatch, backend, tools_enabled=True,
          messages=[{"role": "user", "content": "run ls"}])

    assert runs == []
    assert backend.calls == 1
    assert wire["done"]["cancelled"] is True


def test_uncancelled_turn_reports_final_and_not_cancelled(monkeypatch, wire):
    _turn(monkeypatch, FakeBackend([[text("pong")]]))

    assert ("final", {"text": "pong", "cancelled": False}) in wire["events"]
    assert wire["done"]["cancelled"] is False
