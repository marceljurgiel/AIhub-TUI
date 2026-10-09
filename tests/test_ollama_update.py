"""Is there a newer Ollama than the one AIhub talks to — and how to get it:
updated by AIhub when Ollama runs on this machine, a command to run when it
runs on another one."""
import json
import os
import time

import pytest

from aihub import ollama_update as ou
from aihub.config import config


class R:
    def __init__(self, data, status=200):
        self._d, self.status_code = data, status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(str(self.status_code))

    def json(self):
        return self._d


@pytest.fixture
def net(monkeypatch, tmp_path):
    """A server at 0.30.7, GitHub's latest 0.40.2; counts GitHub calls."""
    monkeypatch.setattr(ou, "CONFIG_DIR", str(tmp_path))
    monkeypatch.setattr(config, "ollama_api_url", "http://gpu-box.lan:11434")
    calls = {"github": 0}
    state = {"server": "0.30.7", "latest": "v0.40.2"}

    def get(url, **k):
        if url.endswith("/api/version"):
            return R({"version": state["server"]})
        if "api.github.com" in url:
            calls["github"] += 1
            return R({"tag_name": state["latest"]})
        raise AssertionError(url)

    monkeypatch.setattr(ou.requests, "get", get)
    monkeypatch.setattr(ou, "is_local", lambda url: "localhost" in url)
    return calls, state


@pytest.mark.parametrize("a,b,newer", [
    ("0.40.2", "0.30.7", True), ("0.30.10", "0.30.7", True), ("0.30.7", "0.30.7", False),
    ("0.30.7", "0.40.2", False), ("0.41.0-rc1", "0.40.2", True), ("v0.40.2", "0.40.2", False),
])
def test_version_order(a, b, newer):
    assert ou.is_newer(a, b) is newer


def test_another_machine_gets_the_command_to_run_there(net):
    out = ou.check()
    assert out["newer"] is True and out["local"] is False
    assert out["server"] == "0.30.7" and out["latest"] == "0.40.2"
    assert out["how"] == "manual" and out["host"] == "gpu-box.lan"
    assert out["command"] == "curl -fsSL https://ollama.com/install.sh | sh"


def test_this_machine_on_linux_is_updated_by_the_installer(net, monkeypatch):
    monkeypatch.setattr(config, "ollama_api_url", "http://localhost:11434")
    monkeypatch.setattr(ou, "_platform", lambda: "linux")
    out = ou.check()
    assert out["local"] is True and out["how"] == "installer"
    assert out["command"] == "curl -fsSL https://ollama.com/install.sh | sh"


def test_this_machine_on_macos_uses_homebrew_or_the_app(net, monkeypatch):
    monkeypatch.setattr(config, "ollama_api_url", "http://localhost:11434")
    monkeypatch.setattr(ou, "_platform", lambda: "darwin")
    monkeypatch.setattr(ou, "_brew_has_ollama", lambda: True)
    assert ou.check()["how"] == "brew" and ou.check()["command"] == "brew upgrade ollama"
    monkeypatch.setattr(ou, "_brew_has_ollama", lambda: False)
    assert ou.check()["how"] == "app"


def test_this_machine_on_windows_is_left_to_ollamas_own_updater(net, monkeypatch):
    monkeypatch.setattr(config, "ollama_api_url", "http://localhost:11434")
    monkeypatch.setattr(ou, "_platform", lambda: "win32")
    assert ou.check()["how"] == "app"


def test_up_to_date_says_so(net):
    _, state = net
    state["server"] = "0.40.2"
    assert ou.check()["newer"] is False


def test_github_is_asked_once_a_day(net):
    calls, _ = net
    ou.check()
    ou.check()
    assert calls["github"] == 1
    path = os.path.join(ou.CONFIG_DIR, "cache", "ollama-latest.json")
    d = json.load(open(path))
    d["checked"] = time.time() - 25 * 3600
    json.dump(d, open(path, "w"))
    ou.check()
    assert calls["github"] == 2


def test_offline_server_or_github_is_no_update(net, monkeypatch):
    def down(url, **k):
        raise ConnectionError("no route")

    monkeypatch.setattr(ou.requests, "get", down)
    out = ou.check()
    assert out["newer"] is False and out["server"] == "" and out["latest"] == ""


def test_bridge_handler(net):
    from aihub import bridge
    assert bridge._ONESHOT["ollama.update_check"]({})["latest"] == "0.40.2"
