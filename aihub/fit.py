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
import os
import platform
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Dict, List, Optional, Tuple

from .hardware import get_gpu_info, get_ram_info

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
