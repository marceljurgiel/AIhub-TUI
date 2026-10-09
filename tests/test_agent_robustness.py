"""Small-model failure modes seen in real sessions."""
import os

from aihub import chat
from aihub.chat import Done, run_chat_turn
from aihub.tools import file_ops, set_user_text
from aihub.tools.remember import remember

from .conftest import SCHEMA, FakeBackend, text, tool_call


def test_read_file_on_a_directory_lists_it(tmp_path):
    (tmp_path / "bin").mkdir()
    (tmp_path / "config.json").write_text("{}")
    out = file_ops.read_file(str(tmp_path))
    assert not out.startswith("[File Error]") and "is a directory" in out
    assert "config.json" in out and "bin/" in out


def test_empty_answer_after_tools_gets_one_nudge(monkeypatch):
    monkeypatch.setattr(chat, "run_tool", lambda name, **kw: "[File Error] nope")
    backend = FakeBackend([[tool_call({"name": "read_file", "args": {"path": "x"}})],
                           [text("")], [text("The file doesn't exist.")]])
    msgs = [{"role": "user", "content": "read x"}]
    events = list(run_chat_turn("m", msgs, tools_schema=SCHEMA, stream_fn=backend))
    assert isinstance(events[-1], Done) and events[-1].final_text == "The file doesn't exist."
    assert not any(m["role"] == "system" for m in msgs)          # the nudge isn't kept
    assert msgs[-1] == {"role": "assistant", "content": "The file doesn't exist."}


def test_nudge_only_once(monkeypatch):
    monkeypatch.setattr(chat, "run_tool", lambda name, **kw: "ok")
    backend = FakeBackend([[tool_call({"name": "read_file", "args": {"path": "x"}})], [text("")], [text("")]])
    events = list(run_chat_turn("m", [{"role": "user", "content": "x"}], tools_schema=SCHEMA, stream_fn=backend))
    assert isinstance(events[-1], Done) and events[-1].final_text == ""


def test_remember_refuses_what_the_user_never_said(monkeypatch):
    from aihub.config import config
    monkeypatch.setattr(config, "memory_enabled", True)
    applied = []
    monkeypatch.setattr("aihub.memory_ops.apply_ops", lambda ops, **kw: applied.extend(ops) or [])
    set_user_text("Lisbon tourist attractions bazujac na wiedzy o mnie, co byś wybrał?")
    out = remember("Editor", "Preferowanie edytorowe Neovima")
    assert out.startswith("[Memory Error] Not saved") and not applied
    set_user_text("zapamiętaj że mój edytor to Neovim")
    remember("Editor", "Uses Neovim")
    assert applied and applied[0]["fact"] == "Uses Neovim"
    set_user_text(None)
