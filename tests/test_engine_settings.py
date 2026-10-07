"""Settings the front-end can change: Ollama server, working directory."""
from __future__ import annotations

import pytest
import requests

from aihub import bridge
from aihub.config import config
from aihub.tools import workdir as wd

from .conftest import FakeBackend, text


@pytest.fixture
def cfg(monkeypatch):
    """Let _h_config_set mutate config safely: restored afterwards, never saved."""
    for field in ("ollama_api_url", "project_dir", "tools_enabled"):
        monkeypatch.setattr(config, field, getattr(config, field))
    saved = []
    monkeypatch.setattr("aihub.config.save_config", lambda c: saved.append(c.model_dump()))
    return saved


@pytest.mark.parametrize("raw,url", [
    ("192.0.2.10", "http://192.0.2.10:11434"),
    ("192.0.2.10:11434", "http://192.0.2.10:11434"),
    ("http://192.0.2.10:11434/", "http://192.0.2.10:11434"),
    (" localhost ", "http://localhost:11434"),
    ("https://ollama.example.com", "https://ollama.example.com"),
    ("http://host:8080", "http://host:8080"),
])
def test_ollama_url_normalisation(raw, url):
    assert bridge._normalize_ollama_url(raw) == url


@pytest.mark.parametrize("raw", ["", "   ", "ftp://host", "http://"])
def test_bad_ollama_urls_rejected(raw):
    with pytest.raises(ValueError):
        bridge._normalize_ollama_url(raw)


def test_config_set_saves_normalised_values(cfg, tmp_path):
    out = bridge._h_config_set({"patch": {"ollama_api_url": "192.0.2.10",
                                          "project_dir": str(tmp_path)}})
    assert config.ollama_api_url == "http://192.0.2.10:11434"
    assert out["project_dir"] == str(tmp_path) and out["workdir"] == str(tmp_path)
    assert cfg[-1]["ollama_api_url"] == "http://192.0.2.10:11434"


def test_config_set_rejects_missing_dir_without_partial_apply(cfg, tmp_path):
    before = config.ollama_api_url
    with pytest.raises(ValueError, match="not a directory"):
        bridge._h_config_set({"patch": {"ollama_api_url": "192.0.2.9",
                                        "project_dir": str(tmp_path / "missing")}})
    assert config.ollama_api_url == before       # nothing applied
    assert cfg == []                             # nothing written


def test_empty_project_dir_means_launch_dir(cfg, monkeypatch, tmp_path):
    monkeypatch.setenv("AIHUB_WORKDIR", str(tmp_path))
    out = bridge._h_config_set({"patch": {"project_dir": ""}})
    assert out["project_dir"] == "" and out["workdir"] == str(tmp_path)


class _Resp:
    def __init__(self, status=200, body=None):
        self.status_code, self._body = status, body or {"version": "0.30.7"}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.exceptions.HTTPError(response=self)

    def json(self):
        if self._body == "html":
            raise ValueError("not json")
        return self._body


@pytest.mark.parametrize("behaviour,expect", [
    (lambda *a, **k: _Resp(), {"ok": True, "version": "0.30.7"}),
    (requests.exceptions.ConnectTimeout(), {"ok": False, "error": "no answer within 4 s"}),
    (requests.exceptions.ConnectionError(), {"ok": False, "error": "connection refused"}),
    (lambda *a, **k: _Resp(404), {"ok": False, "error": "answered HTTP 404"}),
    (lambda *a, **k: _Resp(200, "html"), {"ok": False, "error": "not like an Ollama server"}),
])
def test_ollama_check(monkeypatch, behaviour, expect):
    def fake_get(url, timeout):
        assert url == "http://192.0.2.10:11434/api/version"
        if isinstance(behaviour, Exception):
            raise behaviour
        return behaviour()

    monkeypatch.setattr(requests, "get", fake_get)
    out = bridge._h_ollama_check({"url": "192.0.2.10"})
    assert out["ok"] is expect["ok"] and out["url"] == "http://192.0.2.10:11434"
    if expect["ok"]:
        assert out["version"] == expect["version"]
    else:
        assert expect["error"] in out["error"]


@pytest.fixture
def session_dir(monkeypatch, tmp_path):
    monkeypatch.setattr(wd, "_session_dir", "")
    monkeypatch.setattr(config, "project_dir", "")
    monkeypatch.setenv("AIHUB_WORKDIR", str(tmp_path))
    return tmp_path


def test_cd_sets_session_dir_relative_to_current(session_dir):
    (session_dir / "sub").mkdir()
    assert bridge._h_workdir_set({"path": "sub"}) == {"workdir": str(session_dir / "sub")}
    assert wd.workdir() == str(session_dir / "sub")


def test_cd_beats_project_dir_and_empty_resets(session_dir, monkeypatch, tmp_path_factory):
    proj = tmp_path_factory.mktemp("proj")
    monkeypatch.setattr(config, "project_dir", str(proj))
    other = tmp_path_factory.mktemp("other")
    bridge._h_workdir_set({"path": str(other)})
    assert wd.workdir() == str(other)
    assert bridge._h_workdir_set({"path": ""}) == {"workdir": str(proj)}


def test_cd_to_missing_dir_fails(session_dir):
    with pytest.raises(NotADirectoryError):
        bridge._h_workdir_set({"path": "nope"})
    assert wd.workdir() == str(session_dir)


def test_chat_turn_sees_the_current_working_directory(session_dir, monkeypatch):
    from aihub.memory import build_system_prompt
    system = build_system_prompt()                    # built before /cd
    (session_dir / "later").mkdir()
    bridge._h_workdir_set({"path": "later"})

    seen = {}

    def stream(model, messages, temperature, context_length=None, tools=None):
        seen["system"] = messages[0]["content"]
        return FakeBackend([[text("ok")]])(model, messages, temperature)

    monkeypatch.setattr(bridge, "_resolve_stream_fn", lambda m, b: stream)
    monkeypatch.setattr(bridge, "_emit", lambda *a, **k: None)
    monkeypatch.setattr(bridge, "_done", lambda *a, **k: None)
    bridge._stream_chat_turn(4, {"model": "m", "messages": [
        {"role": "system", "content": system}, {"role": "user", "content": "hi"}]})
    assert f"Working directory: {session_dir / 'later'}" in seen["system"]
    assert seen["system"].count("Environment (") == 1


def test_theme_and_accent_are_saved_and_checked(cfg):
    out = bridge._h_config_set({"patch": {"theme": "Nord", "accent": "blue"}})
    assert out["theme"] == "nord" and out["accent"] == "blue"
    assert bridge._h_config_set({"patch": {"theme": "", "accent": ""}})["theme"] == "aihub"
    with pytest.raises(ValueError, match="not a theme name"):
        bridge._h_config_set({"patch": {"accent": "#ff00ff; rm -rf"}})
