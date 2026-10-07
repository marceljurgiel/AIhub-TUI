"""Tools run in the user's working directory; the model knows its environment."""
from __future__ import annotations

import os

import pytest

from aihub import bridge
from aihub.config import config
from aihub.memory import build_system_prompt
from aihub.tools import workdir as wd
from aihub.tools.file_ops import read_file, write_file
from aihub.tools.terminal import run_terminal

from .conftest import FakeBackend, text


@pytest.fixture
def launch_dir(tmp_path, monkeypatch):
    d = tmp_path / "launched-here"
    d.mkdir()
    monkeypatch.setattr(config, "project_dir", "")
    monkeypatch.setenv("AIHUB_WORKDIR", str(d))
    return d


def test_workdir_precedence(tmp_path, monkeypatch, launch_dir):
    assert wd.workdir() == str(launch_dir)
    proj = tmp_path / "proj"
    proj.mkdir()
    monkeypatch.setattr(config, "project_dir", str(proj))
    assert wd.workdir() == str(proj)                  # project_dir wins
    monkeypatch.setattr(config, "project_dir", str(tmp_path / "missing"))
    assert wd.workdir() == str(launch_dir)            # a missing dir is skipped
    monkeypatch.delenv("AIHUB_WORKDIR")
    monkeypatch.setattr(config, "project_dir", "")
    assert wd.workdir() == os.getcwd()


def test_relative_write_lands_in_workdir_and_reports_full_path(launch_dir):
    out = write_file(".txt", "test")
    assert (launch_dir / ".txt").read_text() == "test"
    assert str(launch_dir / ".txt") in out           # model and user see the real path
    assert "test" in read_file(".txt")


def test_terminal_runs_in_workdir(launch_dir):
    assert str(launch_dir) in run_terminal("pwd")       # PowerShell on Windows: no truncated path


def test_home_paths_still_expand(launch_dir):
    assert wd.resolve("~/x.txt") == os.path.join(os.path.expanduser("~"), "x.txt")
    assert wd.resolve("/abs/y") == os.path.normpath("/abs/y")


@pytest.mark.skipif(os.name == "nt", reason="XDG user dirs are a Linux thing")
def test_localised_desktop_from_user_dirs(tmp_path, monkeypatch):
    home = tmp_path / "home"
    (home / ".config").mkdir(parents=True)
    (home / ".config" / "user-dirs.dirs").write_text('XDG_DESKTOP_DIR="$HOME/Pulpit"\n')
    monkeypatch.setenv("HOME", str(home))
    assert wd.user_dir("DESKTOP", "Desktop") == str(home / "Pulpit")
    assert wd.user_dir("DOCUMENTS", "Documents") == str(home / "Documents")   # fallback


def test_chat_system_prompt_tells_the_model_where_things_are(launch_dir):
    prompt = build_system_prompt()
    assert f"Working directory: {launch_dir}" in prompt
    assert "Desktop: " in prompt and f"Home directory: {os.path.expanduser('~')}" in prompt


def test_config_get_reports_effective_workdir(launch_dir):
    assert bridge._h_config_get({})["workdir"] == str(launch_dir)


def test_agent_turn_uses_agent_prompt_and_restores_history(monkeypatch, launch_dir):
    seen = {}

    def stream(model, messages, temperature, context_length=None, tools=None):
        seen["system"] = messages[0]["content"]
        return FakeBackend([[text("ok")]])(model, messages, temperature)

    monkeypatch.setattr(bridge, "_resolve_stream_fn", lambda m, b: stream)
    monkeypatch.setattr(bridge, "_emit", lambda *a, **k: None)
    done = {}
    monkeypatch.setattr(bridge, "_done", lambda rid, data=None: done.update(data))
    msgs = [{"role": "system", "content": "CHAT PROMPT"}, {"role": "user", "content": "hi"}]
    bridge._stream_chat_turn(9, {"model": "m", "messages": msgs, "agent": True, "submode": "plan"})

    assert "PLAN mode" in seen["system"] and f"Working directory: {launch_dir}" in seen["system"]
    assert done["messages"][0]["content"] == "CHAT PROMPT"


def test_bridge_logs_each_tool_call(monkeypatch, caplog, launch_dir):
    from .conftest import tool_call
    monkeypatch.setattr("aihub.chat.run_tool", lambda name, **kw: "[File OK] Written 4 bytes to: x")
    backend = FakeBackend([[tool_call({"name": "read_file", "args": {"path": "notes.txt"}})], [text("ok")]])
    monkeypatch.setattr(bridge, "_resolve_stream_fn", lambda m, b: backend)
    monkeypatch.setattr(bridge, "_emit", lambda *a, **k: None)
    monkeypatch.setattr(bridge, "_done", lambda *a, **k: None)
    caplog.set_level("INFO", logger="aihub")
    bridge._stream_chat_turn(3, {"model": "m", "agent": True, "submode": "build",
                                 "messages": [{"role": "user", "content": "hi"}]})
    assert 'tool read_file {"path": "notes.txt"} -> ok' in caplog.text
