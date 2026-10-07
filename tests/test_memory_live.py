"""Memory reaches the model on every turn, and the model can add to it."""
from __future__ import annotations

import pytest

from aihub import bridge, memory
from aihub.config import config
from aihub.tools import TOOLS_REGISTRY, TOOLS_SCHEMA, run_tool, wants_tools

from .conftest import FakeBackend, text, tool_call


@pytest.fixture
def mem(tmp_path, monkeypatch):
    path = tmp_path / "memory.md"
    monkeypatch.setattr(memory, "get_memory_path", lambda: str(path))
    monkeypatch.setattr(memory, "_migrate_legacy", lambda: None)
    monkeypatch.setattr(config, "memory_enabled", True)
    return path


def _turn(monkeypatch, messages, backend, agent=False):
    seen = []

    def stream(model, msgs, temperature, context_length=None, tools=None):
        seen.append(msgs[0]["content"])
        return backend(model, msgs, temperature)

    monkeypatch.setattr(bridge, "_resolve_stream_fn", lambda m, b: stream)
    monkeypatch.setattr(bridge, "_emit", lambda *a, **k: None)
    done = {}
    monkeypatch.setattr(bridge, "_done", lambda rid, data=None: done.update(data or {}))
    bridge._stream_chat_turn(1, {"model": "m", "messages": messages, "agent": agent,
                                 "tools_enabled": True})
    return seen, done


def test_memory_turned_on_mid_session_reaches_the_next_turn(mem, monkeypatch):
    mem.write_text("## Name\nAlex\n")
    monkeypatch.setattr(config, "memory_enabled", False)
    history = [{"role": "system", "content": memory.build_system_prompt()},
               {"role": "user", "content": "hi"}]
    assert "Alex" not in history[0]["content"]

    monkeypatch.setattr(config, "memory_enabled", True)       # toggled in Settings
    seen, _ = _turn(monkeypatch, history, FakeBackend([[text("hello Alex")]]))
    assert "Alex" in seen[0]


def test_agent_turns_see_memory_too(mem, monkeypatch):
    mem.write_text("## Name\nAlex\n")
    history = [{"role": "system", "content": "old"}, {"role": "user", "content": "hi"}]
    seen, done = _turn(monkeypatch, history, FakeBackend([[text("ok")]]), agent=True)
    assert "coding agent" in seen[0] and "Alex" in seen[0]
    assert done["messages"][0]["content"] == "old"          # front-end history untouched


def test_history_without_a_system_message_gets_one(mem, monkeypatch):
    mem.write_text("## Name\nAlex\n")
    seen, _ = _turn(monkeypatch, [{"role": "user", "content": "hi"}], FakeBackend([[text("ok")]]))
    assert "Alex" in seen[0]


def test_memory_instructions_ask_for_relevant_use_not_recital(mem):
    mem.write_text("## Name\nAlex\n")
    prompt = memory.build_system_prompt()
    assert "whenever they're relevant" in prompt and "don't recite them unprompted" in prompt


# ── remember tool ─────────────────────────────────────────────────────────────

def test_remember_is_offered_and_saves(mem):
    assert "remember" in TOOLS_REGISTRY
    assert any(t["function"]["name"] == "remember" for t in TOOLS_SCHEMA)
    out = run_tool("remember", topic="Editor", fact="Uses Neovim")
    assert out.startswith("[Memory OK]")
    assert "## Editor\nUses Neovim" in mem.read_text()


def test_remember_adds_to_a_topic_and_replaces_on_a_change(mem):
    run_tool("remember", topic="Editor", fact="Uses Vim")
    run_tool("remember", topic="Editor", fact="Uses VS Code for notebooks")
    assert "Uses Vim\nUses VS Code for notebooks" in mem.read_text()
    run_tool("remember", topic="Editor", fact="Now uses Neovim instead of Vim")
    text_ = mem.read_text()
    assert "Now uses Neovim instead of Vim" in text_ and "Uses Vim\n" not in text_


def test_remember_refuses_when_memory_is_off(mem, monkeypatch):
    monkeypatch.setattr(config, "memory_enabled", False)
    out = run_tool("remember", topic="Editor", fact="Uses Neovim")
    assert out.startswith("[Memory Error]") and "Settings" in out
    assert not mem.exists()


def test_remember_needs_topic_and_fact(mem):
    assert run_tool("remember", topic=" ", fact="x").startswith("[Memory Error]")


def test_saved_fact_is_in_the_next_turns_prompt(mem, monkeypatch):
    backend = FakeBackend([
        [tool_call({"name": "remember", "args": {"topic": "Editor", "fact": "Uses Neovim"}})],
        [text("Saved.")],
        [text("You use Neovim.")],
    ])
    history = [{"role": "user", "content": "Zapamiętaj, że używam Neovima."}]
    _, done = _turn(monkeypatch, history, backend)
    seen, _ = _turn(monkeypatch, done["messages"] + [{"role": "user", "content": "What editor?"}], backend)
    assert "Uses Neovim" in seen[0]


@pytest.mark.parametrize("text_", [
    "Zapamiętaj proszę, że mój ulubiony edytor to Neovim.",
    "remember that I work at night",
    "pamiętaj, że mam psa",
    "nie zapomnij, że jutro mam egzamin",
])
def test_memory_requests_get_tools(text_):
    assert wants_tools([{"role": "user", "content": text_}])
