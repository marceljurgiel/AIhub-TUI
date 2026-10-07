"""Failures are reported or logged instead of silently losing data."""
from __future__ import annotations

import logging
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from aihub import bridge, config as config_mod, history, memory


# ── Config: a bad value must not wipe the rest ────────────────────────────────

def _load(tmp_path, monkeypatch, text):
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text(text)
    monkeypatch.setattr(config_mod, "CONFIG_FILE", str(cfg_file))
    return config_mod.load_config(), cfg_file


def test_one_invalid_field_keeps_the_others(tmp_path, monkeypatch, caplog):
    cfg, _ = _load(tmp_path, monkeypatch, yaml.safe_dump({
        "anthropic_api_key": "sk-keep-me",
        "default_context_length": "not a number",
        "memory_enabled": True,
    }))
    assert cfg.anthropic_api_key == "sk-keep-me"
    assert cfg.memory_enabled is True
    assert cfg.default_context_length == config_mod.AppConfig().default_context_length
    assert "default_context_length" in caplog.text


def test_unparseable_config_is_backed_up(tmp_path, monkeypatch, caplog):
    cfg, cfg_file = _load(tmp_path, monkeypatch, "anthropic_api_key: [unclosed\n")
    backups = list(tmp_path.glob("config.yaml.broken-*"))
    assert len(backups) == 1 and backups[0].read_text() == cfg_file.read_text()
    assert cfg.anthropic_api_key == ""
    assert "could not read" in caplog.text


# ── Memory: an unreadable file is never overwritten ───────────────────────────

@pytest.fixture
def mem_file(tmp_path, monkeypatch):
    path = tmp_path / "memory.md"
    monkeypatch.setattr(memory, "get_memory_path", lambda: str(path))
    monkeypatch.setattr(memory, "_migrate_legacy", lambda: None)
    return path


def test_update_entry_refuses_to_clobber_unreadable_memory(mem_file):
    original = b"## Name\nAlex\n\xff\xfe broken bytes\n"
    mem_file.write_bytes(original)
    with pytest.raises(UnicodeDecodeError):
        memory.update_memory_entry("Editor", "vim")
    assert mem_file.read_bytes() == original


def test_load_memory_degrades_to_empty_and_logs(mem_file, caplog):
    mem_file.write_bytes(b"\xff\xfe")
    assert memory.load_memory() == ""
    assert "could not read memory" in caplog.text


def test_update_entry_still_works_normally(mem_file):
    mem_file.write_text("## Name\nAlex\n")
    memory.update_memory_entry("Editor", "vim")
    text = mem_file.read_text()
    assert "## Name\nAlex" in text and "## Editor\nvim" in text


# ── Sessions: failed save / load reach the front-end ──────────────────────────

MSGS = [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "hello"}]


def test_failed_save_is_an_error_not_nothing_to_save(tmp_path, monkeypatch):
    blocker = tmp_path / "not-a-dir"
    blocker.write_text("x")                  # a file where the history dir goes
    monkeypatch.setattr(history, "get_history_dir", lambda m: str(blocker / "m"))
    with pytest.raises(Exception):
        bridge._h_chat_finalize({"model": "m", "messages": MSGS})


def test_nothing_to_save_is_still_fine(tmp_path, monkeypatch):
    monkeypatch.setattr(history, "get_history_dir", lambda m: str(tmp_path / "m"))
    out = bridge._h_chat_finalize({"model": "m", "messages": [{"role": "system", "content": "s"}]})
    assert out == {"path": ""}


def test_prune_failure_does_not_fail_the_save(tmp_path, monkeypatch, caplog):
    monkeypatch.setattr(history, "get_history_dir", lambda m: str(tmp_path / "m"))

    def boom(model):
        raise OSError("disk says no")

    monkeypatch.setattr(history, "_prune_old_sessions", boom)
    path = history.save_session("m", MSGS)
    assert path and Path(path).exists()
    assert "could not prune" in caplog.text


def test_corrupt_session_file_is_an_error_on_load(tmp_path, monkeypatch):
    d = tmp_path / "m"
    d.mkdir()
    (d / "2026-01-01_00-00-00.json").write_text("{ not json")
    monkeypatch.setattr(history, "get_history_dir", lambda m: str(d))
    with pytest.raises(RuntimeError, match="could not read saved session"):
        bridge._h_history_load({"model": "m", "filename": "2026-01-01_00-00-00.json"})


def test_corrupt_session_is_skipped_in_list_with_a_warning(tmp_path, monkeypatch, caplog):
    d = tmp_path / "m"
    d.mkdir()
    (d / "bad.json").write_text("{ nope")
    monkeypatch.setattr(history, "get_history_dir", lambda m: str(d))
    assert history.list_sessions("m") == []
    assert "skipping unreadable session file" in caplog.text


# ── Bridge: engine logs reach stderr (→ the OpenTUI error log) ────────────────

def test_bridge_sends_engine_warnings_to_stderr():
    code = (
        "import sys, threading\n"
        "from aihub import bridge\n"
        "sys.stdin = __import__('io').StringIO('not json\\n')\n"
        "bridge.main()\n"
    )
    proc = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=60)
    assert '"event": "ready"' in proc.stdout
    assert "ignoring malformed request line" in proc.stderr
    assert "ignoring malformed" not in proc.stdout      # protocol channel stays clean
