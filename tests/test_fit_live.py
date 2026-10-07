"""Honest model fit: real hardware, learned server speed, live catalogs."""
from __future__ import annotations

import os
import subprocess

import pytest

from aihub import bridge, catalog, fit, hardware, target
from aihub.config import config

FIX = os.path.join(os.path.dirname(__file__), "fixtures")


def _page(name):
    with open(os.path.join(FIX, name), encoding="utf-8") as f:
        return f.read()


# ── hardware: never invent VRAM ───────────────────────────────────────────────

def test_rocm_smi_package_alone_is_not_an_amd_gpu(monkeypatch):
    """Intel-only laptop with the rocm-smi package installed used to report a
    made-up 8 GB Radeon."""
    monkeypatch.setattr(hardware.shutil, "which",
                        lambda c: "/usr/bin/" + c if c in ("rocm-smi", "lspci") else None)
    monkeypatch.setattr(hardware, "_rocm_smi_json", lambda args: None)
    lspci = ("00:02.0 VGA compatible controller: Intel Corporation UHD Graphics 620\n"
             "3d:00.0 Non-Volatile memory controller: Samsung NVMe (AMD platform)\n")
    monkeypatch.setattr(hardware.subprocess, "check_output", lambda *a, **k: lspci)
    import sys
    gpu = hardware.get_gpu_info()
    assert gpu["vendor"] == "Intel" and gpu["vram_total_mb"] == 0


def test_lspci_gpu_without_vram_info_reports_unknown_not_8gb(monkeypatch):
    monkeypatch.setattr(hardware.shutil, "which", lambda c: "/usr/bin/lspci" if c == "lspci" else None)
    monkeypatch.setattr(hardware.subprocess, "check_output",
                        lambda *a, **k: "03:00.0 VGA compatible controller: Advanced Micro Devices, Inc. [AMD/ATI] Rembrandt\n")
    import sys
    gpu = hardware.get_gpu_info()
    assert gpu["vendor"] == "AMD" and gpu["vram_total_mb"] == 0


# ── catalog parsing + cache ──────────────────────────────────────────────────

def test_parse_library():
    models = {m["name"]: m for m in catalog.parse_library(_page("ollama_library.html"))}
    g = models["gemma4"]
    assert {"vision", "tools", "thinking"} <= set(g["capabilities"])
    assert g["sizes"] == ["e2b", "e4b", "12b", "26b", "31b"]
    assert g["pulls"] > 1_000_000 and "ago" in g["updated"]
    assert "embedding" in models["nomic-embed-text"]["capabilities"]


def test_parse_tags_real_sizes():
    tags = catalog.parse_tags(_page("ollama_tags_gemma4.html"), "gemma4")
    assert tags["12b"] == {"size_gb": 7.7, "context": 262144}
    assert tags["e4b"]["size_gb"] == 6.6


@pytest.mark.parametrize("tag,expected", [
    ("8b", {"params_b": 8.0}), ("270m", {"params_b": 0.27}),
    ("e4b", {"params_b": 4.0, "effective": 1.0}), ("26b-a4b", {"params_b": 26.0, "active_b": 4.0}),
    ("latest", None), ("70b-instruct-q4_K_M", None),
])
def test_parse_size_tag(tag, expected):
    assert catalog.parse_size_tag(tag) == expected


class _Resp:
    def __init__(self, text="", js=None):
        self.text, self._js = text, js

    def raise_for_status(self):
        pass

    def json(self):
        return self._js


def test_refresh_ollama_caches_and_reuses_fresh_tags(monkeypatch):
    calls = []

    def fake_get(url, **kw):
        calls.append(url)
        if url.endswith("/tags"):
            return _Resp(_page("ollama_tags_gemma4.html"))
        return _Resp(_page("ollama_library.html"))

    monkeypatch.setattr(catalog.requests, "get", fake_get)
    data = catalog.refresh_ollama()
    gemma = next(m for m in data["models"] if m["name"] == "gemma4")
    assert gemma["variants"]["12b"]["size_gb"] == 7.7
    assert catalog.ollama_models()["age_s"] == 0
    first = sum(u.endswith("/tags") for u in calls)
    catalog.refresh_ollama()                                  # tags still fresh → not refetched
    assert sum(u.endswith("/tags") for u in calls) == first


def test_refresh_survives_one_source_failing(monkeypatch):
    def fake_get(url, **kw):
        if "huggingface" in url:
            raise OSError("offline")
        return _Resp(_page("ollama_tags_gemma4.html") if url.endswith("/tags") else _page("ollama_library.html"))

    monkeypatch.setattr(catalog.requests, "get", fake_get)
    out = catalog.refresh()
    assert out["ollama"]["count"] == 4 and "error" in out["hf"]


def test_hf_refresh_keeps_trusted_publishers(monkeypatch):
    js = [
        {"id": "unsloth/Qwen3-4B-GGUF", "author": "unsloth", "gguf": {"total": 4.0e9, "architecture": "qwen3"}, "downloads": 9},
        {"id": "someone/Qwen-Uncensored-GGUF", "author": "someone", "gguf": {"total": 4.0e9}, "downloads": 99},
        {"id": "unsloth/Qwen3-30B-A3B-GGUF", "author": "unsloth", "gguf": {"total": 30.5e9}, "downloads": 5},
    ]
    monkeypatch.setattr(catalog.requests, "get", lambda url, **kw: _Resp(js=js))
    models = catalog.refresh_hf()["models"]
    assert [m["id"] for m in models] == ["unsloth/Qwen3-4B-GGUF", "unsloth/Qwen3-30B-A3B-GGUF"]
    assert models[1]["active_b"] == 3.0


# ── target profile ───────────────────────────────────────────────────────────

SERVER = "http://192.0.2.10:11434"


@pytest.fixture
def server(monkeypatch):
    monkeypatch.setattr(config, "ollama_api_url", SERVER)
    monkeypatch.setattr(config, "ollama_gpu_memory_gb", 0.0)
    return SERVER


def test_server_defaults_are_labelled_assumed(server):
    t = target.current()
    assert t.where == "server" and t.vram_basis == "assumed" and t.bw_basis == "estimated"


def test_server_learns_speed_and_vram_from_chats(server):
    gib = 1024 ** 3
    target.record_sample(SERVER, "qwen3:8b", 6.8, int(5.2 * gib), int(5.2 * gib))   # fully on GPU
    target.record_sample(SERVER, "llama3.2:3b", 16.0, int(2.3 * gib), int(2.3 * gib))
    t = target.current()
    assert t.bw_basis == "measured" and 34 <= t.bw_eff <= 37      # median of 35.4, 36.8
    assert t.vram_basis == "learned" and t.vram_gb >= 5.2
    assert t.shared_memory                                         # iGPU-class bandwidth
    target.record_sample(SERVER, "gemma4:12b", 3.0, int(7.6 * gib), int(6.9 * gib))  # partly offloaded
    assert target.current().vram_gb == pytest.approx(6.9, abs=0.05)
    assert target.measured_tps(SERVER, "qwen3:8b") == 6.8


def test_setting_overrides_learned_vram(server, monkeypatch):
    monkeypatch.setattr(config, "ollama_gpu_memory_gb", 12.0)
    assert target.current().vram_gb == 12.0 and target.current().vram_basis == "setting"


def test_local_target_uses_real_hardware(monkeypatch):
    monkeypatch.setattr(config, "ollama_api_url", "http://localhost:11434")
    monkeypatch.setattr(config, "ollama_gpu_memory_gb", 0.0)
    monkeypatch.setattr("aihub.hardware.get_gpu_info", lambda: {"vendor": "Intel", "model": "UHD 620", "vram_total_mb": 0})
    monkeypatch.setattr("aihub.hardware.get_ram_info", lambda: {"total_gb": 15.4})
    t = target.current()
    assert t.where == "local" and t.vram_gb == 0 and t.ram_gb == 15.4 and "UHD 620" in t.label


# ── estimates + ranking ─────────────────────────────────────────────────────

IGPU = target.Target("server", "server", 8.0, "learned", 0.0, 35.0, "measured", True)


def test_speed_estimate_matches_measured_server_speeds():
    """qwen3:8b (5.2 GB) ran 6.5–8 tok/s on the user's server."""
    est = fit.estimate(5.2, IGPU)
    assert est["placement"] == "gpu" and 5.5 <= est["est_tps"] <= 8.5


def test_moe_speed_uses_active_params():
    dense = fit.estimate(18.0, target.Target("server", "s", 24.0, "setting", 0, 35.0, "measured", True))
    moe = fit.estimate(18.0, target.Target("server", "s", 24.0, "setting", 0, 35.0, "measured", True), active_gb=1.8)
    assert moe["est_tps"] > 3 * dense["est_tps"]
    # lfm2.5:8b (4.8 GB, ~1B active) measured 28 t/s at ~37 GB/s: the
    # estimate must be in that range, not 60+.
    lfm = fit.estimate(4.8, target.Target("server", "s", 8.0, "setting", 0, 37.0, "measured", True), active_gb=0.6)
    assert 20 <= lfm["est_tps"] <= 40


def test_bandwidth_learned_from_dense_weights_one_vote_per_model(monkeypatch, tmp_path):
    monkeypatch.setattr(target, "_store_path", lambda: str(tmp_path / "servers.json"))
    gib = 1024 ** 3
    url = "http://srv:11434"
    for _ in range(10):      # chatted a lot with the MoE model: it must not count
        target.record_sample(url, "lfm2.5:8b", 28.9, int(5.3 * gib), int(5.3 * gib), weights_gb=4.8, moe=True)
    target.record_sample(url, "qwen3:8b", 6.5, int(6.9 * gib), int(6.9 * gib), weights_gb=4.87)
    target.record_sample(url, "llama3.2:3b", 22.7, int(3.8 * gib), int(3.8 * gib), weights_gb=1.88)
    prof = target._server_target(url, 0)
    assert 30 <= prof.bw_eff <= 45 and prof.bw_basis == "measured"


def test_too_big_does_not_fit():
    assert fit.estimate(19.0, IGPU)["fits"] is False


def _cand(name, params, size, updated="2 months ago", pulls=10_000_000, caps=("tools",)):
    return {"name": name, "params_b": params, "active_b": None, "size_gb": size,
            "updated": updated, "pulls": pulls, "capabilities": list(caps)}


def test_ranking_prefers_capable_current_models_that_run_well():
    rows = {c["name"]: fit.assess(c, IGPU) for c in [
        _cand("modern:8b", 8.0, 5.2),
        _cand("tiny:0.6b", 0.6, 0.5),
        _cand("old:7b", 7.0, 3.8, updated="2 years ago"),
        _cand("sqlcoder:7b", 7.0, 4.1, caps=()),
        _cand("huge:32b", 32.0, 19.0),
    ]}
    abs_ = {k: r["score_abs"] for k, r in rows.items()}       # independent of the catalog
    assert abs_["modern:8b"] > abs_["tiny:0.6b"]
    assert abs_["modern:8b"] > abs_["old:7b"]
    assert abs_["modern:8b"] > abs_["sqlcoder:7b"]
    assert abs_["huge:32b"] == 0
    assert all(v < 100 for v in abs_.values())                 # no saturation at 100


def test_recent_beats_old_popular_and_guards_are_skipped():
    old = _cand("llama3.1:8b", 8.0, 4.9, updated="1 year ago", pulls=120_000_000)
    new = _cand("qwen3.5:9b", 9.0, 6.0, updated="3 minutes ago", pulls=2_000_000)
    assert fit.assess(new, IGPU)["score_abs"] > fit.assess(old, IGPU)["score_abs"]
    lib = [{"name": "granite4.1-guardian", "capabilities": ["tools"], "sizes": ["8b"], "variants": {}},
           {"name": "granite4.1", "capabilities": ["tools"], "sizes": ["8b"], "variants": {}}]
    assert [c["family"] for c in fit.ollama_candidates(lib)] == ["granite4.1"]


def test_measured_speed_replaces_the_estimate():
    r = fit.assess(_cand("qwen3:8b", 8.0, 5.2), IGPU, measured=6.8)
    assert r["est_tps"] == 6.8 and r["basis"] == "measured"


def test_candidates_skip_embedding_and_cloud_only():
    models = [
        {"name": "nomic-embed-text", "capabilities": ["embedding"], "sizes": ["137m"]},
        {"name": "glm-cloud", "capabilities": ["cloud"], "sizes": []},
        {"name": "qwen3", "capabilities": ["tools"], "sizes": ["8b"], "variants": {"8b": {"size_gb": 5.2}}},
    ]
    assert [c["name"] for c in fit.ollama_candidates(models)] == ["qwen3:8b"]


# ── bridge ───────────────────────────────────────────────────────────────────

def test_bridge_recommend_and_library_from_cache(server, monkeypatch):
    monkeypatch.setattr(catalog.requests, "get", lambda url, **kw: _Resp(
        _page("ollama_tags_gemma4.html") if url.endswith("/tags") else _page("ollama_library.html")))
    catalog.refresh_ollama()
    monkeypatch.setattr(catalog.requests, "get", lambda *a, **k: pytest.fail("no network on read"))
    rec = bridge._h_models_recommend({})
    assert rec["target"]["where"] == "server" and rec["models"]
    assert all(m["family"] != "nomic-embed-text" for m in rec["models"])
    lib = bridge._h_ollama_library({"query": "gemma"})
    assert [m["name"] for m in lib["models"]] == ["gemma4"]
    assert lib["models"][0]["best"]["fit"]["fits"]


def test_chat_turn_records_a_speed_sample(server, monkeypatch):
    from .conftest import FakeBackend
    chunks = [{"message": {"content": "hi"}},
              {"message": {"content": ""}, "eval_count": 70, "eval_duration": 10_000_000_000, "prompt_eval_count": 5}]
    monkeypatch.setattr(bridge, "_resolve_stream_fn", lambda m, b: FakeBackend([chunks]))
    monkeypatch.setattr(bridge, "_emit", lambda *a, **k: None)
    monkeypatch.setattr(bridge, "_done", lambda *a, **k: None)
    gib = 1024 ** 3
    monkeypatch.setattr("aihub.ollama_client.get_running_models",
                        lambda: [{"name": "qwen3:8b", "size": int(5.2 * gib), "size_vram": int(5.2 * gib)}])
    # No network: model sizes and /api/show (MoE check) are faked too.
    monkeypatch.setattr("aihub.ollama_client.get_local_model_sizes", lambda: {"qwen3:8b": 4.87})

    class Show:
        def json(self):
            return {"model_info": {"qwen3.block_count": 36}}
    monkeypatch.setattr("requests.post", lambda *a, **k: Show())
    bridge._stream_chat_turn(1, {"model": "qwen3:8b", "messages": [{"role": "user", "content": "x"}]})
    assert target.measured_tps(SERVER, "qwen3:8b") == 7.0


def test_hf_search_row_infers_params_from_size():
    from aihub import bridge
    from aihub.target import Target
    tgt = Target("server", "server x", 8.0, "assumed", 0.0, 35.0, "estimated", True)
    row = bridge._hf_row("someone/Model-GGUF", 0.0, None, 4.8, {}, tgt)
    assert row["params_b"] == 8.0
    assert row["fit"]["fits"] and row["fit"]["score"] > 20


def test_scores_are_relative_to_the_best_model_for_this_machine(monkeypatch):
    lib = {"models": [
        {"name": "big", "capabilities": ["tools"], "sizes": ["12b"], "variants": {"12b": {"size_gb": 7.0}},
         "pulls": 10_000_000, "updated": "1 month ago"},
        {"name": "small", "capabilities": ["tools"], "sizes": ["3b"], "variants": {"3b": {"size_gb": 2.0}},
         "pulls": 10_000_000, "updated": "1 month ago"},
        {"name": "giant", "capabilities": ["tools"], "sizes": ["70b"], "variants": {"70b": {"size_gb": 40.0}},
         "pulls": 10_000_000, "updated": "1 month ago"},
    ], "age_s": 10}
    monkeypatch.setattr("aihub.catalog.ollama_models", lambda: lib)
    fit._REF_CACHE.clear()
    tgt = target.Target("server", "s", 8.0, "setting", 0, 40.0, "measured", True)
    rows = {r["name"]: r["fit"] for r in fit.recommend_live(tgt)["models"]}
    assert rows["big:12b"]["score"] == 100                       # the best that fits = 100
    assert 0 < rows["small:3b"]["score"] < 100
    assert rows["small:3b"]["score_abs"] < rows["small:3b"]["score"]
    assert rows["giant:70b"]["score"] == 0
