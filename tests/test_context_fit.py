"""Context sizing uses the model's real dimensions, and a context that doesn't
fit the server's memory is retried smaller instead of failing the turn."""
import json

import pytest

from aihub import ollama_client


class Resp:
    def __init__(self, status=200, body=None, lines=()):
        self.status_code, self._body, self._lines = status, body or {}, lines
        self.ok = status < 400
        self.text, self.reason = json.dumps(self._body), "error"

    def json(self):
        return self._body

    def raise_for_status(self):
        if not self.ok:
            raise RuntimeError(self.status_code)

    def iter_lines(self):
        return iter(self._lines)

    def close(self):
        pass


@pytest.fixture(autouse=True)
def fresh_caches(monkeypatch):
    monkeypatch.setattr(ollama_client, "_kv_cache", {})
    monkeypatch.setattr(ollama_client, "_kv_down", {})
    monkeypatch.setattr(ollama_client, "_ctx_cap", {})
    monkeypatch.setattr(ollama_client.config, "ollama_api_url", "http://192.0.2.10:11434")


def test_kv_bytes_from_model_dimensions(monkeypatch):
    info = {"general.architecture": "llama", "llama.block_count": 28, "llama.attention.head_count": 24,
            "llama.attention.head_count_kv": 8, "llama.attention.key_length": 128,
            "llama.attention.value_length": 128, "llama.embedding_length": 3072}
    monkeypatch.setattr(ollama_client.requests, "post", lambda *a, **k: Resp(body={"model_info": info}))
    per_token = ollama_client.kv_bytes_per_token("llama3.2:3b")
    assert per_token == 28 * 8 * 256 * 2
    from aihub.hardware import estimate_kv_cache_gb
    assert estimate_kv_cache_gb(65536, "llama3.2:3b") == 7.0   # what the server really allocated


def test_hybrid_model_counts_attention_layers_only(monkeypatch):
    info = {"general.architecture": "qwen35", "qwen35.block_count": 32, "qwen35.attention.head_count": 16,
            "qwen35.attention.head_count_kv": None, "qwen35.attention.key_length": 256,
            "qwen35.attention.value_length": 256, "qwen35.full_attention_interval": 4}
    monkeypatch.setattr(ollama_client.requests, "post", lambda *a, **k: Resp(body={"model_info": info}))
    assert ollama_client.kv_bytes_per_token("qwen3.5:9b") == 8 * 16 * 512 * 2


def test_unknown_dimensions_fall_back_to_the_heuristic(monkeypatch):
    def down(*a, **k):
        raise ConnectionError("down")
    monkeypatch.setattr(ollama_client.requests, "post", down)
    assert ollama_client.kv_bytes_per_token("llama3.2:3b") is None
    from aihub.hardware import estimate_kv_cache_gb
    assert estimate_kv_cache_gb(8192, "mystery-7b") == 1.1


def test_out_of_memory_retries_with_half_the_context(monkeypatch):
    sent = []

    def post(url, json=None, **k):
        sent.append(json["options"]["num_ctx"])
        if json["options"]["num_ctx"] > 16384:
            return Resp(500, {"error": "llama-server process has terminated: cudaMalloc failed: out of memory"})
        return Resp(lines=[b'{"message": {"content": "hi"}, "done": true}'])

    monkeypatch.setattr(ollama_client.requests, "post", post)
    out = list(ollama_client.chat_stream("m", [{"role": "user", "content": "x"}], context_length=65536))
    assert sent == [65536, 32768, 16384]
    assert out == [{"message": {"content": "hi"}, "done": True}]
    # The next turn starts at what fit.
    sent.clear()
    list(ollama_client.chat_stream("m", [{"role": "user", "content": "x"}], context_length=65536))
    assert sent == [16384]


def test_other_errors_are_not_retried(monkeypatch):
    calls = []

    def post(url, json=None, **k):
        calls.append(1)
        return Resp(404, {"error": "model 'm' not found"})

    monkeypatch.setattr(ollama_client.requests, "post", post)
    out = list(ollama_client.chat_stream("m", [], context_length=8192))
    assert calls == [1] and out == [{"error": "404: model 'm' not found"}]


def test_local_ollama_is_started_when_installed_but_down(monkeypatch):
    import subprocess
    monkeypatch.setattr(ollama_client.config, "ollama_api_url", "http://localhost:11434")
    up = iter([False, False, True])
    monkeypatch.setattr(ollama_client, "is_ollama_running", lambda: next(up))
    monkeypatch.setattr(ollama_client, "_ollama_binary", lambda: "/opt/ollama/bin/ollama")
    spawned = []
    monkeypatch.setattr(subprocess, "Popen", lambda argv, **k: spawned.append(argv))
    monkeypatch.setattr("aihub.config.CONFIG_DIR", str(__import__("tempfile").mkdtemp()))
    assert ollama_client.start_local_ollama(wait_s=2) is True
    assert spawned == [["/opt/ollama/bin/ollama", "serve"]]


def test_a_remote_server_is_never_started(monkeypatch):
    import subprocess
    monkeypatch.setattr(ollama_client, "is_ollama_running", lambda: False)
    monkeypatch.setattr(ollama_client, "_ollama_binary", lambda: "/opt/ollama/bin/ollama")
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: (_ for _ in ()).throw(AssertionError("spawned")))
    assert ollama_client.start_local_ollama(wait_s=0) is False   # 192.0.2.10 from the fixture


def _target(where, vram, ram):
    from aihub.target import Target
    return Target(where, "t", vram, "detected", ram, 50.0, "estimated", False)


def test_cpu_only_machine_gets_a_usable_context(monkeypatch):
    from aihub import hardware
    monkeypatch.setattr("aihub.target.current", lambda: _target("local", 0.0, 6.0))
    monkeypatch.setattr(ollama_client, "get_local_model_sizes", lambda: {"gemma3:1b": 0.8})
    monkeypatch.setattr(ollama_client, "kv_bytes_per_token", lambda m: 26 * 512 * 2)
    assert hardware.recommend_context("gemma3:1b") == 8192        # capped for CPU speed


def test_cpu_only_with_little_ram_keeps_the_default(monkeypatch):
    from aihub import hardware
    monkeypatch.setattr("aihub.target.current", lambda: _target("local", 0.0, 2.0))
    monkeypatch.setattr(ollama_client, "get_local_model_sizes", lambda: {"big:8b": 4.9})
    monkeypatch.setattr(ollama_client, "kv_bytes_per_token", lambda m: 36 * 8 * 256 * 2)
    assert hardware.recommend_context("big:8b") == ollama_client.config.default_context_length


def test_a_down_server_is_not_asked_again_for_every_context_step(monkeypatch):
    import requests
    calls = []

    def refused(*a, **k):
        calls.append(1)
        raise requests.exceptions.ConnectionError("refused")
    monkeypatch.setattr(ollama_client.requests, "post", refused)
    assert ollama_client.kv_bytes_per_token("a:1b") is None
    assert ollama_client.kv_bytes_per_token("b:7b") is None
    assert calls == [1]
