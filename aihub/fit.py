"""
AIHub — hardware model-fit engine.

A pure-Python port of the core ideas from llmfit (https://github.com/AlexsJones/llmfit,
MIT). Given the detected hardware, for each model in the vendored catalog it picks
the best quantization that fits (walking Q8_0 → Q2_K, with a half-context fallback),
classifies the run mode, estimates tokens/sec, and scores the fit. `recommend()`
returns models ranked best-fit first.

The model catalog lives in `aihub/data/llmfit_models.json` (vendored & trimmed from
llmfit's `data/hf_models.json` — see `aihub/data/LICENSE-llmfit`).
"""
from __future__ import annotations

import json
import logging
import os
import platform
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Dict, List, Optional, Tuple

from .hardware import get_gpu_info, get_ram_info

log = logging.getLogger(__name__)

_DB_PATH = os.path.join(os.path.dirname(__file__), "data", "llmfit_models.json")

# Approximate bits-per-weight for each quantization, highest quality first.
# (Same hierarchy llmfit walks: Q8_0 → … → Q2_K.)
_QUANT_HIERARCHY: List[Tuple[str, float]] = [
    ("q8_0",   8.5),
    ("q6_k",   6.6),
    ("q5_k_m", 5.7),
    ("q4_k_m", 4.8),
    ("q3_k_m", 3.4),
    ("q2_k",   2.6),
]
_OVERHEAD = 1.20            # weights + runtime overhead multiplier
_EFFICIENCY = 0.55         # llmfit's bandwidth→throughput efficiency factor


@dataclass(frozen=True)
class FitResult:
    fits: bool
    best_quant: str            # e.g. "q4_k_m" — "" if nothing fits
    run_mode: str              # "gpu" | "cpu+gpu" | "cpu" | "moe" | "none"
    size_gb: float             # on-disk / in-memory size at best_quant
    context: int               # context the fit was computed at
    est_tps: float             # estimated tokens/sec
    score: int                 # 0–100 overall fit score


@lru_cache(maxsize=1)
def load_catalog() -> List[Dict[str, Any]]:
    """Load the vendored model catalog (cached). Never raises."""
    try:
        with open(_DB_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except Exception:
        log.error("could not load model catalog %s", _DB_PATH, exc_info=True)
        return []


# ── Hardware snapshot ──────────────────────────────────────────────────────────

@dataclass(frozen=True)
class HW:
    vram_gb: float
    ram_gb: float
    bandwidth: float           # GB/s, used for the speed estimate
    has_gpu: bool


def detect_hw() -> HW:
    gpu = get_gpu_info()
    ram = get_ram_info()
    vram_gb = round((gpu.get("vram_total_mb") or 0) / 1024.0, 1)
    vendor = (gpu.get("vendor") or "").lower()
    has_gpu = vram_gb > 0
    if "nvidia" in vendor:
        bw = 220.0
    elif "amd" in vendor:
        bw = 180.0
    elif "apple" in vendor or "metal" in vendor:
        bw = 160.0
    else:
        bw = 90.0 if platform.machine().lower() in ("arm64", "aarch64") else 70.0
    return HW(
        vram_gb=vram_gb,
        ram_gb=round((ram.get("total_gb") or 0.0), 1),
        bandwidth=bw,
        has_gpu=has_gpu,
    )


# ── Size / KV math ───────────────────────────────────────────────────────────

def model_size_gb(params_raw: float, bits_per_weight: float) -> float:
    """Approximate in-memory size of the weights at a given quant."""
    if not params_raw:
        return 0.0
    return params_raw * bits_per_weight / 8.0 / (1024 ** 3) * _OVERHEAD


def _kv_cache_gb(entry: Dict[str, Any], context: int) -> float:
    """Rough KV-cache size for a context window, scaled by model dim."""
    hidden = entry.get("hidden_size") or 0
    layers = entry.get("num_hidden_layers") or 0
    if hidden and layers:
        # 2 (K+V) * layers * hidden * 2 bytes (fp16) per token
        return context * layers * hidden * 2 * 2 / (1024 ** 3)
    # Fallback heuristic: ~1 GB per 8k tokens for a 7-9B-class model, scaled.
    params_b = (entry.get("parameters_raw") or 0) / 1e9
    scale = max(0.1, params_b / 8.0)
    return (context / 8192.0) * scale


# ── Fit ─────────────────────────────────────────────────────────────────────

def fit_model(entry: Dict[str, Any], hw: Optional[HW] = None) -> FitResult:
    """Pick the best quant that fits `hw`, with a half-context fallback."""
    hw = hw or detect_hw()
    params = entry.get("parameters_raw") or 0
    is_moe = bool(entry.get("is_moe"))
    # MoE: all weights occupy memory, but only active params drive compute speed.
    speed_params = (entry.get("active_parameters") or params) if is_moe else params
    full_ctx = entry.get("context_length") or 4096

    budget_gpu = hw.vram_gb
    budget_cpu = hw.ram_gb * 0.75    # leave headroom for the OS

    for context in (full_ctx, max(2048, full_ctx // 2)):
        kv = _kv_cache_gb(entry, context)
        for quant, bits in _QUANT_HIERARCHY:
            size = model_size_gb(params, bits)
            need = size + kv
            if hw.has_gpu and need <= budget_gpu:
                mode = "moe" if is_moe else "gpu"
                return _result(True, quant, mode, size, context, speed_params, hw, entry)
            if need <= budget_cpu:
                mode = "moe" if is_moe else ("cpu+gpu" if hw.has_gpu else "cpu")
                return _result(True, quant, mode, size, context, speed_params, hw, entry)
    # Nothing fits even at the smallest quant / half context.
    smallest = _QUANT_HIERARCHY[-1]
    size = model_size_gb(params, smallest[1])
    return _result(False, smallest[0], "none", size, full_ctx, speed_params, hw, entry)


def _result(fits, quant, mode, size, context, speed_params, hw, entry) -> FitResult:
    # Speed: memory-bandwidth bound. CPU modes are much slower.
    speed_size = model_size_gb(speed_params, dict(_QUANT_HIERARCHY)[quant]) or 0.1
    tps = (hw.bandwidth / speed_size) * _EFFICIENCY
    if mode in ("cpu", "cpu+gpu"):
        tps *= 0.25
    if not fits:
        tps = 0.0
    return FitResult(
        fits=fits, best_quant=quant, run_mode=mode, size_gb=round(size, 2),
        context=context, est_tps=round(tps, 1),
        score=_score(fits, quant, mode, context, entry),
    )


def _score(fits, quant, mode, context, entry) -> int:
    if not fits:
        return 0
    # Quality from quant rank (q8 best → q2 worst), fit/speed from run mode.
    quant_rank = {q: i for i, (q, _) in enumerate(reversed(_QUANT_HIERARCHY))}
    quality = quant_rank.get(quant, 0) / (len(_QUANT_HIERARCHY) - 1)   # 0..1
    mode_factor = {"gpu": 1.0, "moe": 0.9, "cpu+gpu": 0.6, "cpu": 0.4}.get(mode, 0.0)
    ctx_factor = min(1.0, context / 8192.0)
    use_case = (entry.get("use_case") or "").lower()
    # Reasoning/coding favour quality; chat favours speed (run mode).
    if any(k in use_case for k in ("reason", "code", "math")):
        w_q, w_m, w_c = 0.55, 0.30, 0.15
    else:
        w_q, w_m, w_c = 0.30, 0.55, 0.15
    return int(round(100 * (w_q * quality + w_m * mode_factor + w_c * ctx_factor)))


def recommend(
    limit: int = 30,
    capability: Optional[str] = None,
    hw: Optional[HW] = None,
) -> List[Tuple[Dict[str, Any], FitResult]]:
    """Return (entry, FitResult) pairs ranked best-fit first."""
    hw = hw or detect_hw()
    out: List[Tuple[Dict[str, Any], FitResult]] = []
    for entry in load_catalog():
        if capability and capability not in (entry.get("capabilities") or []):
            continue
        out.append((entry, fit_model(entry, hw)))
    # Fitting models first, then by score, then by quality (bigger params as tiebreak).
    out.sort(key=lambda p: (p[1].fits, p[1].score, p[0].get("parameters_raw") or 0),
             reverse=True)
    return out[:limit]


# ══ Live fit (OpenTUI picker) ════════════════════════════════════════════════
# Works on the live catalog (aihub/catalog.py) against the machine that runs
# Ollama (aihub/target.py). The functions above stay for the Textual TUI.

Q4_GIB_PER_B = 0.6          # q4_K_M ≈ 0.6 GiB per billion params (incl. embeddings)
RUNTIME_GB = 0.6            # KV cache at a moderate context + compute buffers
CPU_BW = 25.0               # effective GB/s when layers run from system RAM


def estimate(size_gb: float, target, active_gb: Optional[float] = None) -> Dict[str, Any]:
    """Where a model of `size_gb` would run on `target` and how fast.
    `active_gb`: bytes read per token for MoE models (active params only)."""
    import math
    need = size_gb * 1.05 + RUNTIME_GB
    vram = target.vram_gb
    spare_ram = max(target.ram_gb * 0.6, 8.0) if target.ram_gb else 8.0
    # MoE: only the active experts are read per token, but routing, shared
    # layers and attention add a lot — measured lfm2.5:8b (8B, ~1B active)
    # runs like a ~1.2 GB dense model, not a 0.6 GB one.
    read = max(max(active_gb * 1.5, size_gb * 0.25) if active_gb else size_gb, 0.05)
    if vram and need <= vram:
        placement, tps = "gpu", target.bw_eff / read
    elif need <= vram + spare_ram:
        if vram:
            placement = "partial"
            if target.shared_memory:
                tps = target.bw_eff / read * 0.85
            else:
                gpu_part = min(1.0, vram / need)
                tps = 1.0 / (read * gpu_part / target.bw_eff + read * (1 - gpu_part) / CPU_BW)
        else:
            placement, tps = "cpu", min(target.bw_eff, CPU_BW) / read
    else:
        return {"fits": False, "placement": "none", "est_tps": 0.0, "need_gb": round(need, 1)}
    return {"fits": True, "placement": placement, "est_tps": round(tps, 1),
            "need_gb": round(need, 1), "_tps_raw": tps if math.isfinite(tps) else 0.0}


def _freshness(updated: str) -> float:
    """Newer models are much better per parameter: a 2-year-old 7B loses to a
    current 4B. 'updated' is ollama.com's "N units ago"."""
    import re as _re
    m = _re.match(r"(\d+|an?|one)\s+(second|minute|hour|day|week|month|year)", (updated or "").lower())
    if not m:
        return 0.85
    n = 1 if m.group(1) in ("a", "an", "one") else int(m.group(1))
    unit = m.group(2)
    if unit in ("second", "minute", "hour", "day", "week"):
        return 1.05
    if unit == "month":
        return 1.05 if n <= 3 else 1.0 if n <= 6 else 0.88
    return {1: 0.7}.get(n, 0.5 if n == 2 else 0.4)


def live_score(params_b: float, est: Dict[str, Any], updated: str = "", pulls: int = 0,
               capabilities: Optional[List[str]] = None) -> int:
    """'The most capable model that runs well here', 0–100.
      capability  log of size, 32B ≈ 1 (bigger models answer better)
      speed       1 at ≥ 8 tok/s (faster than reading), down to 0.5 at 3,
                  0.15 below — a model you wait on is a poor pick
      placement   GPU 1, partly offloaded 0.85, CPU 0.6
      popularity  0.9–1.0 from log10(all-time pulls) — only a tie-breaker:
                  ollama.com's counts favour models that are simply old
      generality  tool-calling models (general assistants; AIHub uses
                  tools) ×1.0, others ×0.85 — keeps SQL/OCR/translation
                  specialists below general models
      freshness   strong: 1.05 up to 3 months … 0.7 a year, 0.4 for 3+ years"""
    import math
    if not est.get("fits"):
        return 0
    capability = min(1.0, math.log2(1 + max(params_b, 0.05)) / math.log2(33))
    tps = est["est_tps"]
    speed = 1.0 if tps >= 8 else (0.5 + 0.5 * (tps - 3) / 5 if tps >= 3 else 0.15)
    place = {"gpu": 1.0, "partial": 0.85, "cpu": 0.6}.get(est["placement"], 0.0)
    pop = 0.9 + 0.1 * min(1.0, math.log10(max(pulls, 1)) / 8) if pulls else 0.9
    general = 1.0 if (capabilities is None or "tools" in capabilities) else 0.85
    return int(round(min(100.0, 100 * capability * speed * place * pop * general * _freshness(updated))))


def ollama_candidates(models: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """One candidate per runnable size variant of each library model."""
    import re as _re
    from .catalog import parse_size_tag
    out = []
    for m in models:
        caps = m.get("capabilities") or []
        if "embedding" in caps or not m.get("sizes"):
            continue                         # embedding-only / cloud-only
        if _re.search(r"guard|shield", m["name"]):
            continue                         # safety classifiers, not assistants
        variants = m.get("variants") or {}
        for tag in m["sizes"]:
            p = parse_size_tag(tag) or {}
            exact = variants.get(tag, {}).get("size_gb")
            params = p.get("params_b", 0.0)
            size = exact or round(params * Q4_GIB_PER_B, 2)
            active = p.get("active_b")
            out.append({
                "name": f"{m['name']}:{tag}", "family": m["name"], "tag": tag,
                "params_b": params, "active_b": active, "size_gb": size,
                "size_basis": "exact" if exact else "estimated",
                "capabilities": caps, "pulls": m.get("pulls", 0), "updated": m.get("updated", ""),
                "description": m.get("description", ""),
            })
    return out


def _assess_abs(candidate: Dict[str, Any], target, measured: Optional[float] = None) -> Dict[str, Any]:
    active_gb = (candidate["active_b"] * Q4_GIB_PER_B) if candidate.get("active_b") else None
    est = estimate(candidate["size_gb"], target, active_gb)
    if measured and est["fits"]:
        est["est_tps"], basis = measured, "measured"
    else:
        basis = "estimated"
    est.pop("_tps_raw", None)
    return {**est, "basis": basis,
            "score_abs": live_score(candidate.get("params_b", 0.0), est, candidate.get("updated", ""),
                                    candidate.get("pulls", 0), candidate.get("capabilities"))}


_REF_CACHE: Dict[Any, Tuple[float, float]] = {}
_REF_TTL = 60.0


def reference_score(target) -> float:
    """The best absolute score any Ollama-library model gets on `target` —
    the "100" of the relative scale. 0 when there is no catalog (offline,
    first run): scores then stay absolute."""
    import time as _time
    from . import catalog, target as target_mod
    from .config import config
    cat = catalog.ollama_models()
    key = (target.where, target.vram_gb, target.bw_eff, target.ram_gb, target.shared_memory, cat["age_s"] is None)
    hit = _REF_CACHE.get(key)
    if hit and _time.time() - hit[0] < _REF_TTL:
        return hit[1]
    best = 0.0
    for c in ollama_candidates(cat["models"]):
        measured = target_mod.measured_tps(config.ollama_api_url, c["name"])
        best = max(best, _assess_abs(c, target, measured)["score_abs"])
    _REF_CACHE[key] = (_time.time(), float(best))
    return float(best)


def assess(candidate: Dict[str, Any], target, measured: Optional[float] = None) -> Dict[str, Any]:
    """Fit + score for one candidate. `score` is relative to this machine:
    100 = the best pick in the Ollama library for it, the rest a share of
    that (an 8 GB GPU's best model is 100 too, not "42 out of a 32B ideal").
    `score_abs` keeps the absolute 0–100 (32B, fast and current = 100)."""
    out = _assess_abs(candidate, target, measured)
    ref = reference_score(target) if out["score_abs"] else 0.0
    out["score"] = min(100, int(round(100 * out["score_abs"] / ref))) if ref else out["score_abs"]
    return out


def recommend_live(target=None, limit: int = 60) -> Dict[str, Any]:
    """Ranked fit for the machine running Ollama, from the live catalog."""
    from . import catalog, target as target_mod
    from .config import config
    tgt = target or target_mod.current()
    cat = catalog.ollama_models()
    rows = []
    for c in ollama_candidates(cat["models"]):
        measured = target_mod.measured_tps(config.ollama_api_url, c["name"])
        rows.append({**c, "fit": assess(c, tgt, measured)})
    rows.sort(key=lambda r: (r["fit"]["fits"], r["fit"]["score"], r["pulls"]), reverse=True)
    return {"target": tgt.to_dict(), "catalog_age_s": cat["age_s"], "models": rows[:limit]}
