"""Mutating tools need approval outside agent Build — in the CLI and the
bridge the app talks to."""
from __future__ import annotations

import pytest

from aihub import bridge, chat_cli
from aihub.agent import MUTATING, permission_for

from .conftest import FakeBackend, text, tool_call


# ── Policy ────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("tool", sorted(MUTATING))
def test_mutating_tools_ask_in_chat_and_plan_only(tool):
    assert permission_for("chat", tool) == "ask"
    assert permission_for("plan", tool) == "ask"
    assert permission_for("build", tool) == "allow"


@pytest.mark.parametrize("mode", ["chat", "plan", "build"])
def test_read_only_tools_never_ask(mode):
    assert permission_for(mode, "read_file") == "allow"


@pytest.fixture
def tool_runs(monkeypatch):
    runs = []

    def fake_run_tool(name, **kwargs):
        runs.append((name, kwargs))
        return "tool output"

    monkeypatch.setattr("aihub.chat.run_tool", fake_run_tool)
    return runs


# ── CLI ───────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("answer,expected", [("y", True), ("yes", True), ("", False), ("n", False)])
def test_cli_prompts_before_mutating_tool(monkeypatch, answer, expected):
    prompts = []

    def fake_input(prompt=""):
        prompts.append(prompt)
        return answer

    monkeypatch.setattr(chat_cli.console, "input", fake_input)
    assert chat_cli._approve_tool("run_terminal", {"command": "ls"}) is expected
    assert len(prompts) == 1


def test_cli_denies_on_eof(monkeypatch):
    def eof(prompt=""):
        raise EOFError

    monkeypatch.setattr(chat_cli.console, "input", eof)
    assert chat_cli._approve_tool("write_file", {"path": "x"}) is False


def test_cli_read_only_tool_does_not_prompt(monkeypatch):
    def boom(prompt=""):
        raise AssertionError("should not prompt")

    monkeypatch.setattr(chat_cli.console, "input", boom)
    assert chat_cli._approve_tool("read_file", {"path": "x"}) is True


# ── Bridge ────────────────────────────────────────────────────────────────────

def test_bridge_chat_mode_asks_before_shell(monkeypatch, tool_runs):
    backend = FakeBackend([
        [tool_call({"name": "run_terminal", "args": {"command": "echo hi"}})],
        [text("fine")],
    ])
    monkeypatch.setattr(bridge, "_resolve_stream_fn", lambda m, b: backend)
    emitted = []

    def fake_emit(req_id, event, data=None):
        emitted.append(event)
        if event == "permission_request":
            bridge._perm_queues[req_id].put(False)   # front-end says no

    monkeypatch.setattr(bridge, "_emit", fake_emit)
    monkeypatch.setattr(bridge, "_done", lambda req_id, data=None: None)

    bridge._stream_chat_turn(1, {
        "model": "m", "backend": "ollama", "agent": False, "tools_enabled": True,
        "messages": [{"role": "user", "content": "run echo hi"}],
    })

    assert "permission_request" in emitted
    assert tool_runs == []
