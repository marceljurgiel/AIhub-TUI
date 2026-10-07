"""
AIHub — the machine that actually runs the models.

Fit, speed estimates and context sizing must describe the computer behind
the configured Ollama — which may be a server, not the PC running AIHub.
Ollama has no API for its hardware, so for a remote server we LEARN it:

  * after each chat turn the bridge records the measured generation speed
    and how much of the model sat in GPU memory (`/api/ps`);
  * speed → effective memory bandwidth (tok/s × GB read per token), which
    predicts the speed of any other model: tps ≈ bandwidth / model size;
  * a model fully on the GPU bounds VRAM from below; a partly offloaded one
    shows the real limit.

A Settings value ("Ollama GPU memory") overrides the learned VRAM. Until
anything is learned, conservative defaults are used and labelled "assumed".
Learned profiles live in ~/.aihub/cache/servers.json, keyed by Ollama URL.
"""
from __future__ import annotations

import ipaddress
import json
import logging
import os
import socket
import statistics
import time
from dataclasses import asdict, dataclass
from typing import Any, Dict, Optional
from urllib.parse import urlparse

from .config import CONFIG_DIR

log = logging.getLogger(__name__)

GIB = 1024 ** 3
MAX_SAMPLES = 20

# Effective (not theoretical) bandwidths, GB/s: what tok/s × model-size
# measures in practice. Calibrated on a test server: a Radeon 680M iGPU
# on DDR5 runs qwen3:8b (5.2 GiB) at ~6.5–8 tok/s → ~35–40 GB/s.
DEFAULT_BW = {"nvidia": 250.0, "amd": 200.0, "apple": 150.0, "shared": 35.0, "cpu": 25.0}
ASSUMED_SERVER_VRAM_GB = 8.0


@dataclass(frozen=True)
class Target:
    where: str            # "local" | "server"
    label: str            # human description for the picker header
    vram_gb: float        # usable GPU memory, 0 = none
    vram_basis: str       # detected | setting | learned | assumed | none
    ram_gb: float         # system RAM (0 = unknown)
    bw_eff: float         # effective GB/s for the speed estimate
    bw_basis: str         # measured | estimated
    shared_memory: bool   # GPU uses system RAM (iGPU/APU): offload costs little

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ── where is Ollama? ─────────────────────────────────────────────────────────

def _local_addresses() -> set:
    addrs = {"localhost", "127.0.0.1", "::1", "0.0.0.0", socket.gethostname()}
    try:
        import psutil
        for nics in psutil.net_if_addrs().values():
            for a in nics:
                addrs.add(a.address.split("%")[0])
    except Exception:
        pass
    return addrs


def is_local(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    if host in _local_addresses():
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


# ── learned server profiles ──────────────────────────────────────────────────

def _store_path() -> str:
    return os.path.join(CONFIG_DIR, "cache", "servers.json")


def _load() -> Dict[str, Any]:
    try:
        with open(_store_path(), encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except FileNotFoundError:
        return {}
    except Exception:
        log.warning("servers.json unreadable — starting fresh", exc_info=True)
        return {}


def _save(data: Dict[str, Any]) -> None:
    path = _store_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=1)
    os.replace(tmp, path)


def record_sample(url: str, model: str, tps: float, size_bytes: int, size_vram_bytes: int,
                  weights_gb: float = 0.0, moe: bool = False) -> None:
    """One measured chat turn: generation speed + where the model was.
    `size_bytes` is the loaded size (weights + KV cache), which says where
    the model sits; speed per byte uses `weights_gb` (what is read per token).
    MoE models read only their active experts, so they teach no bandwidth."""
    if tps <= 0 or size_bytes <= 0:
        return
    data = _load()
    prof = data.setdefault(url, {})
    size_gb = size_bytes / GIB
    vram_gb = size_vram_bytes / GIB
    on_gpu = size_vram_bytes >= size_bytes * 0.99
    if not moe:
        samples = prof.setdefault("bw_samples", [])
        samples.append(round(tps * (weights_gb or size_gb), 2))
        del samples[:-MAX_SAMPLES]
    if on_gpu:
        prof["vram_full_max_gb"] = round(max(prof.get("vram_full_max_gb", 0.0), vram_gb), 2)
    elif size_vram_bytes > 0:
        prof["vram_partial_gb"] = round(vram_gb, 2)
    prof.setdefault("models", {})[model] = {
        "tps": round(tps, 1), "size_gb": round(size_gb, 2), "weights_gb": round(weights_gb, 2),
        "moe": moe, "on_gpu": on_gpu, "at": int(time.time()),
    }
    prof["updated"] = int(time.time())
    _save(data)


def measured_tps(url: str, model: str) -> Optional[float]:
    m = _load().get(url, {}).get("models", {}).get(model)
    return m.get("tps") if m else None


# ── the profile ──────────────────────────────────────────────────────────────

def current() -> Target:
    """Profile of the machine behind config.ollama_api_url."""
    from .config import config
    url = config.ollama_api_url
    setting = float(getattr(config, "ollama_gpu_memory_gb", 0) or 0)
    if is_local(url):
        return _local_target(setting)
    return _server_target(url, setting)


def _local_target(setting: float) -> Target:
    from .hardware import get_gpu_info, get_ram_info
    gpu = get_gpu_info()
    ram = float(get_ram_info().get("total_gb") or 0.0)
    vendor = (gpu.get("vendor") or "").lower()
    vram = round((gpu.get("vram_total_mb") or 0) / 1024.0, 1)
    shared = vram == 0 or vendor == "intel"
    if setting:
        vram, basis = setting, "setting"
    else:
        basis = "detected" if vram else "none"
    bw = DEFAULT_BW["cpu"] if not vram else (
        DEFAULT_BW["nvidia"] if "nvidia" in vendor else DEFAULT_BW["amd"] if "amd" in vendor
        else DEFAULT_BW["shared"])
    label = f"this computer · {gpu.get('model') or 'CPU'}"
    return Target("local", label, vram, basis, ram, bw, "estimated", shared)


def _server_target(url: str, setting: float) -> Target:
    prof = _load().get(url, {})
    samples = prof.get("bw_samples") or []
    # One value per dense model (its latest speed × weights): a model chatted
    # with a lot can't outvote the others, and MoE models (fast for their
    # size) don't count at all.
    per_model = [m["tps"] * (m.get("weights_gb") or m["size_gb"])
                 for m in (prof.get("models") or {}).values()
                 if not m.get("moe") and m.get("tps") and (m.get("weights_gb") or m.get("size_gb"))]
    if per_model:
        bw, bw_basis = round(statistics.median(per_model), 1), "measured"
    elif samples:
        bw, bw_basis = round(statistics.median(samples), 1), "measured"
    else:
        bw, bw_basis = DEFAULT_BW["shared"], "estimated"
    if setting:
        vram, basis = setting, "setting"
    elif prof.get("vram_partial_gb"):
        vram, basis = prof["vram_partial_gb"], "learned"
    elif prof.get("vram_full_max_gb"):
        # Lower bound; the true size is at least this — and usually one
        # common carve-out step above it.
        vram, basis = max(prof["vram_full_max_gb"], ASSUMED_SERVER_VRAM_GB), "learned"
    else:
        vram, basis = ASSUMED_SERVER_VRAM_GB, "assumed"
    # A discrete GPU measures well above ~80 GB/s; below that it's an iGPU /
    # APU sharing system RAM, where spilling layers to the CPU costs little.
    shared = bw < 80
    host = urlparse(url).hostname or url
    return Target("server", f"server {host}", round(vram, 1), basis, 0.0, bw, bw_basis, shared)
