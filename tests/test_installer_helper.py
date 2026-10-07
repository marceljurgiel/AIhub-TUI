"""aihub.installer is what install.sh / install.ps1 call for Ollama setup."""
import pytest

from aihub import installer


@pytest.mark.parametrize("given,expected", [
    ("192.0.2.10", "http://192.0.2.10:11434"),
    ("gpu-box.lan:8080", "http://gpu-box.lan:8080"),
    ("http://gpu-box.lan/", "http://gpu-box.lan:11434"),
    ("https://ollama.example.com:443", "https://ollama.example.com:443"),
    ("  localhost  ", "http://localhost:11434"),
])
def test_normalize(given, expected):
    assert installer.normalize(given) == expected


def test_server_saves_the_normalized_url(monkeypatch, capsys):
    saved = []
    monkeypatch.setattr("aihub.config.save_config", lambda cfg: saved.append(cfg.ollama_api_url))
    monkeypatch.setattr(installer, "check", lambda url: True)
    from aihub.config import config
    monkeypatch.setattr(config, "ollama_api_url", "http://localhost:11434")
    assert installer.main(["server", "192.0.2.10"]) == 0
    assert saved == ["http://192.0.2.10:11434"]
    assert capsys.readouterr().out.strip() == "http://192.0.2.10:11434"


def test_check_is_false_when_nothing_answers(monkeypatch):
    def down(*a, **k):
        raise ConnectionError
    monkeypatch.setattr(installer.requests, "get", down)
    assert installer.check("http://192.0.2.10:11434") is False
    assert installer.models("http://192.0.2.10:11434") == 0
