"""A context window set by hand for one model (Settings → c) wins over the
automatic sizing — in chat, in agents and in scheduled tasks."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from aihub import agents, bridge, hardware
from aihub.config import config


@pytest.fixture(autouse=True)
def overrides(monkeypatch):
    monkeypatch.setattr(config, "context_overrides", {})
    # Automatic sizing without hardware or network: a remote server with no
    # GPU known falls back to the configured default.
    monkeypatch.setattr("aihub.target.current", lambda: SimpleNamespace(vram_gb=0, ram_gb=0, where="remote",
                                                                         vram_basis="test"))
    monkeypatch.setattr(config, "default_context_length", 2048)
    monkeypatch.setattr("aihub.bridge.save_config", lambda c: None, raising=False)
    monkeypatch.setattr("aihub.config.save_config", lambda c: None)
    return config.context_overrides


def test_manual_context_wins_over_the_automatic_size(overrides):
    overrides["llama3.2:3b"] = 16384
    assert hardware.recommend_context("llama3.2:3b") == 16384
    assert hardware.recommend_context("gemma3:1b") == 2048          # other models stay automatic


def test_manual_context_is_capped_by_the_model_maximum(overrides):
    overrides["llama3.2:3b"] = 65536
    assert hardware.recommend_context("llama3.2:3b", hard_cap=32768) == 32768


def test_recommend_context_handler_reports_manual_and_what_fits(overrides):
    assert bridge._ONESHOT["hardware.recommend_context"]({"model": "llama3.2:3b"}) == \
        {"context": 2048, "manual": 0, "fits": 2048}
    overrides["llama3.2:3b"] = 24576
    assert bridge._ONESHOT["hardware.recommend_context"]({"model": "llama3.2:3b"}) == \
        {"context": 24576, "manual": 24576, "fits": 2048}


def test_agents_use_the_manual_context(overrides):
    overrides["llama3.2:3b"] = 16384
    assert agents.agent_context("llama3.2:3b", "ollama", None) == (16384, "manual")
    assert agents.agent_context("llama3.2:3b", "ollama", None, max_context=8192) == (8192, "manual")


def test_agents_are_warned_about_a_small_manual_context(overrides):
    overrides["llama3.2:3b"] = 4096
    ctx, note = agents.agent_context("llama3.2:3b", "ollama", None)
    assert ctx == 4096
    assert "below 8K" in note


def test_context_set_saves_and_auto_removes(monkeypatch, overrides):
    monkeypatch.setattr("aihub.ollama_client.get_model_info", lambda m: {"max_context": 131072})
    out = bridge._ONESHOT["context.set"]({"model": "llama3.2:3b", "context": 24576})
    assert out == {"model": "llama3.2:3b", "manual": 24576, "note": ""}
    assert config.context_overrides == {"llama3.2:3b": 24576}
    out = bridge._ONESHOT["context.set"]({"model": "llama3.2:3b", "context": 0})
    assert out["manual"] == 0
    assert config.context_overrides == {}


def test_context_set_clamps_to_the_model_maximum(monkeypatch, overrides):
    monkeypatch.setattr("aihub.ollama_client.get_model_info", lambda m: {"max_context": 8192})
    out = bridge._ONESHOT["context.set"]({"model": "llama3.2:3b", "context": 32768})
    assert out["manual"] == 8192
    assert "8,192" in out["note"]
    assert config.context_overrides == {"llama3.2:3b": 8192}


@pytest.mark.parametrize("bad", [100, -1, "lots", 2_000_000])
def test_context_set_rejects_nonsense(monkeypatch, bad):
    monkeypatch.setattr("aihub.ollama_client.get_model_info", lambda m: {})
    with pytest.raises(ValueError, match="512"):
        bridge._ONESHOT["context.set"]({"model": "llama3.2:3b", "context": bad})


def test_config_drops_broken_override_entries():
    from aihub.config import AppConfig
    c = AppConfig(context_overrides={"a": 8192, "b": "x", "c": -5})
    assert c.context_overrides == {"a": 8192}
