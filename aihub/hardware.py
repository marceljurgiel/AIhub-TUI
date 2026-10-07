"""
AIHub - Hardware detection module.
Collects full device specs: GPU, CPU, RAM, Disk, OS.
Used to rank models by hardware compatibility and estimate inference speed.
"""
import json
import platform
import re
import shutil
import subprocess
from typing import Any, Dict, Optional

import psutil


def get_cpu_info() -> Dict[str, Any]:
    """Return CPU model, physical and logical core counts, base/boost clock, and current usage."""
    brand = platform.processor() or "Unknown CPU"
    try:
        import cpuinfo
        info = cpuinfo.get_cpu_info()
        brand = info.get("brand_raw", brand)
        hz = info.get("hz_advertised_friendly", "")
        if hz and hz not in brand:
            brand = f"{brand} ({hz})"
    except Exception:
        pass

    return {
        "model":          brand,
        "cores_physical": psutil.cpu_count(logical=False) or 1,
        "cores_logical":  psutil.cpu_count(logical=True)  or 1,
        "usage_percent":  psutil.cpu_percent(interval=0.1),
    }


def get_ram_info() -> Dict[str, Any]:
    """Return total, available RAM in GB and usage percentage."""
    ram = psutil.virtual_memory()
    return {
        "total_gb":     round(ram.total     / (1024 ** 3), 2),
        "available_gb": round(ram.available / (1024 ** 3), 2),
        "percent_used": ram.percent,
    }


def get_disk_info() -> Dict[str, Any]:
    """Return total and free disk space in GB for the root/system drive."""
    # Cross-platform root path
    root = "C:\\" if platform.system() == "Windows" else "/"
    try:
        usage = psutil.disk_usage(root)
        return {
            "total_gb":    round(usage.total / (1024 ** 3), 2),
            "free_gb":     round(usage.free  / (1024 ** 3), 2),
            "percent_used": usage.percent,
        }
    except Exception:
        return {"total_gb": 0, "free_gb": 0, "percent_used": 0}


def _rocm_smi_json(args: str) -> Optional[Dict[str, Any]]:
    """Run `rocm-smi <args> --json` and return the parsed dict, or None.

    stderr is always discarded — rocm-smi prints its full usage text on any
    unrecognized flag, which would corrupt the Textual screen if it leaked
    to the terminal.
    """
    try:
        out = subprocess.check_output(
            f"rocm-smi {args} --json",
            shell=True, text=True, stderr=subprocess.DEVNULL,
        )
        data = json.loads(out[out.index("{"):])
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def _rocm_first_card(data: Dict[str, Any]) -> Dict[str, Any]:
    """First per-card dict from rocm-smi JSON ({'card0': {...}, ...})."""
    for key, val in data.items():
        if key.lower().startswith("card") and isinstance(val, dict):
            return val
    return {}


def _rocm_find(card: Dict[str, Any], *needles: str) -> Optional[str]:
    """Value of the first key containing all needles (case-insensitive).
    rocm-smi key names vary across ROCm versions."""
    for key, val in card.items():
        low = key.lower()
        if all(n.lower() in low for n in needles):
            return str(val)
    return None


def _windows_registry_vram() -> dict:
    """{adapter name: VRAM bytes} from the display drivers' registry keys."""
    out = {}
    try:
        import winreg
        base = r"SYSTEM\CurrentControlSet\Control\Class\{4d36e968-e325-11ce-bfc1-08002be10318}"
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, base) as cls:
            for i in range(winreg.QueryInfoKey(cls)[0]):
                sub = winreg.EnumKey(cls, i)
                if not sub.isdigit():
                    continue
                try:
                    with winreg.OpenKey(cls, sub) as k:
                        name = winreg.QueryValueEx(k, "DriverDesc")[0]
                        size = winreg.QueryValueEx(k, "HardwareInformation.qwMemorySize")[0]
                    if isinstance(size, bytes):
                        size = int.from_bytes(size, "little")
                    out[str(name)] = max(out.get(str(name), 0), int(size))
                except OSError:
                    continue
    except Exception:
        pass
    return out


def get_gpu_info() -> Dict[str, Any]:
    """
    Detect GPU vendor, model, and VRAM.
    Tries NVIDIA (nvidia-smi), then AMD (rocm-smi), then lspci fallback.
    On Windows falls back to wmi if neither tool is available.
    """
    # ── NVIDIA ──────────────────────────────────────────────────────────────
    if shutil.which("nvidia-smi"):
        try:
            out = subprocess.check_output(
                "nvidia-smi --query-gpu=name,memory.total,memory.free --format=csv,noheader",
                shell=True, text=True, stderr=subprocess.DEVNULL,
            ).strip().split("\n")
            if out and out[0]:
                parts = [p.strip() for p in out[0].split(",")]
                return {
                    "vendor":       "NVIDIA",
                    "model":        parts[0],
                    "vram_total_mb": int(parts[1].replace(" MiB", "")),
                    "vram_free_mb":  int(parts[2].replace(" MiB", "")),
                }
        except Exception:
            pass

    # ── AMD (ROCm) ──────────────────────────────────────────────────────────
    # Note: some rocm-smi versions don't have --showvram; --showmeminfo vram
    # is the portable spelling, and --json keeps output parseable.
    if shutil.which("rocm-smi"):
        data = (_rocm_smi_json("--showproductname --showmeminfo vram")
                or _rocm_smi_json("--showmeminfo vram"))
        if data:
            card = _rocm_first_card(data)
            model = (_rocm_find(card, "card series")
                     or _rocm_find(card, "product name")
                     or "AMD Radeon GPU (via rocm-smi)")
            total_b = _rocm_find(card, "vram", "total memory")
            used_b  = _rocm_find(card, "vram", "used memory")
            try:
                total_mb = int(int(total_b) / (1024 * 1024)) if total_b else 0
                used_mb  = int(int(used_b)  / (1024 * 1024)) if used_b else 0
            except (TypeError, ValueError):
                total_mb, used_mb = 0, 0
            if total_mb:
                return {
                    "vendor":       "AMD",
                    "model":        model,
                    "vram_total_mb": total_mb,
                    "vram_free_mb":  max(total_mb - used_mb, 0),
                }
        # rocm-smi installed but reporting nothing is NOT an AMD GPU: the
        # package alone is common (it used to make an Intel-only laptop
        # report a made-up 8 GB Radeon). Fall through to lspci.

    # ── Windows: wmi ─────────────────────────────────────────────────────────
    if platform.system() == "Windows":
        try:
            import warnings
            with warnings.catch_warnings():   # wmi's docstrings trip SyntaxWarning
                warnings.simplefilter("ignore", SyntaxWarning)
                import wmi
            w = wmi.WMI()
            for controller in w.Win32_VideoController():
                try:
                    vram_bytes = int(controller.AdapterRAM) if controller.AdapterRAM else 0
                except:
                    vram_bytes = 0
                # AdapterRAM is 32-bit (caps at 4 GB); the driver's registry
                # entry has the real size.
                vram_bytes = max(vram_bytes, _windows_registry_vram().get(str(controller.Name), 0))
                vram_mb = vram_bytes // (1024 * 1024)
                name_low = str(controller.Name).lower()
                vendor = "NVIDIA" if "nvidia" in name_low else "AMD" if "amd" in name_low else "Intel" if "intel" in name_low else "Unknown"
                if vram_mb > 0 or vendor != "Unknown":
                    return {
                        "vendor": vendor,
                        "model": controller.Name,
                        "vram_total_mb": max(vram_mb, 0),
                        "vram_free_mb": max(vram_mb, 0),
                    }
        except Exception:
            pass

    # ── lspci fallback (Linux) ───────────────────────────────────────────────
    if shutil.which("lspci"):
        try:
            out = subprocess.check_output(
                "lspci", shell=True, text=True, stderr=subprocess.DEVNULL,
            )
            # Only display controllers count, and lspci can't tell VRAM:
            # report the device with vram 0 (unknown) rather than guess.
            displays = [l for l in out.splitlines()
                        if re.search(r"VGA compatible|3D controller|Display controller", l)]
            text = " ".join(displays).lower()
            name = displays[0].split(": ", 1)[-1].strip() if displays else ""
            if "nvidia" in text:
                return {"vendor": "NVIDIA", "model": name or "NVIDIA GPU", "vram_total_mb": 0, "vram_free_mb": 0}
            if re.search(r"\b(amd|ati|radeon)\b", text):
                return {"vendor": "AMD", "model": name or "AMD Radeon", "vram_total_mb": 0, "vram_free_mb": 0}
            if "intel" in text:
                return {"vendor": "Intel", "model": name or "Intel integrated graphics",
                        "vram_total_mb": 0, "vram_free_mb": 0}
        except Exception:
            pass

    return {
        "vendor":       "Unknown",
        "model":        "No dedicated GPU detected",
        "vram_total_mb": 0,
        "vram_free_mb":  0,
    }


def get_gpu_usage() -> Dict[str, Any]:
    """
    Live GPU utilization + VRAM. Returns
        {util_percent, vram_used_mb, vram_total_mb}
    or {} when no usable GPU is detected.
    """
    if shutil.which("nvidia-smi"):
        try:
            out = subprocess.check_output(
                "nvidia-smi --query-gpu=utilization.gpu,memory.used,memory.total "
                "--format=csv,noheader,nounits",
                shell=True, text=True, stderr=subprocess.DEVNULL,
            ).strip().split("\n")
            if out and out[0]:
                util, used, total = [p.strip() for p in out[0].split(",")]
                return {
                    "util_percent":  float(util),
                    "vram_used_mb":  float(used),
                    "vram_total_mb": float(total),
                }
        except Exception:
            pass
    # AMD: rocm-smi --json exposes live use% + VRAM on ROCm 4+.
    if shutil.which("rocm-smi"):
        data = _rocm_smi_json("-u --showmeminfo vram") or _rocm_smi_json("--showmeminfo vram")
        if data:
            card = _rocm_first_card(data)
            util    = _rocm_find(card, "gpu use")
            total_b = _rocm_find(card, "vram", "total memory")
            used_b  = _rocm_find(card, "vram", "used memory")
            try:
                if total_b:
                    return {
                        "util_percent":  float(util) if util not in (None, "N/A") else -1.0,
                        "vram_used_mb":  float(int(used_b) / (1024 * 1024)) if used_b else 0.0,
                        "vram_total_mb": float(int(total_b) / (1024 * 1024)),
                    }
            except (TypeError, ValueError):
                pass

    # Fallback: totals from static detection only.
    gpu = get_gpu_info()
    if gpu.get("vram_total_mb"):
        used = gpu["vram_total_mb"] - gpu.get("vram_free_mb", gpu["vram_total_mb"])
        return {
            "util_percent":  -1.0,   # unknown
            "vram_used_mb":  float(max(0, used)),
            "vram_total_mb": float(gpu["vram_total_mb"]),
        }
    return {}


def get_cpu_usage() -> float:
    """Instantaneous CPU utilization % (non-blocking — since the last call)."""
    try:
        return psutil.cpu_percent(interval=None)
    except Exception:
        return 0.0


def get_os_info() -> str:
    """Return a human-readable OS description."""
    return platform.platform()


def score_hardware(required_vram_gb: float) -> bool:
    """
    Return True if the current hardware can run a model with the given VRAM requirement.
    Falls back to system RAM if no dedicated GPU is detected.
    """
    gpu    = get_gpu_info()
    if gpu["vram_total_mb"] == 0:
        ram = get_ram_info()
        return ram["available_gb"] >= (required_vram_gb * 1.5)
    return (gpu["vram_total_mb"] / 1024.0) >= required_vram_gb


def estimate_tokens_per_sec(model_vram_required: float) -> str:
    """
    Heuristic estimate of inference tokens/sec based on detected GPU and model size.

    Returns a human-readable string like '~40-60 t/s (GPU)'.
    """
    gpu     = get_gpu_info()
    vram_gb = gpu["vram_total_mb"] / 1024.0

    if gpu["vram_total_mb"] == 0:
        return "~3-8 t/s (CPU)" if model_vram_required <= 4 else "< 2 t/s (CPU)"

    if vram_gb >= model_vram_required:
        vendor = gpu["vendor"].upper()
        if "NVIDIA" in vendor or "AMD" in vendor:
            return "~40-80 t/s (GPU)"
        return "~15-30 t/s (iGPU)"

    return "~5-15 t/s (partial offload)"


def get_available_ram_gb() -> float:
    """
    Return the effective hardware RAM limit for model selection (in GB).
    - If a discrete GPU is detected: returns total VRAM in GB
    - If only CPU/iGPU: returns 75% of available system RAM (safe headroom)

    This is used by the model browser to filter and rank models by best-fit.
    """
    gpu = get_gpu_info()
    if gpu["vram_total_mb"] > 0:
        return round(gpu["vram_total_mb"] / 1024.0, 1)
    # CPU-only: use 75% of available RAM as a safe working estimate
    ram = get_ram_info()
    return round(ram["available_gb"] * 0.75, 1)


def estimate_kv_cache_gb(context_size: int, model_name: str = "") -> float:
    """
    Estimate the VRAM/RAM (KV Cache) usage for a given context size in GB.
    Exact from the model's dimensions when Ollama has the model; otherwise a
    heuristic: ~1GB per 8192 tokens for standard 7B-9B models.
    """
    if model_name:
        from .ollama_cloud import is_cloud
        if not is_cloud(model_name):
            from .ollama_client import kv_bytes_per_token
            per_token = kv_bytes_per_token(model_name)
            if per_token:
                return round(context_size * per_token / 1024 ** 3, 2)
    # Baseline for 7B-9B models: 1GB per 8k
    gb_per_8k = 1.0
    
    # Adjust based on model name keywords
    name_lower = model_name.lower()
    if any(k in name_lower for k in ["72b", "70b", "405b"]):
        gb_per_8k = 4.5
    elif any(k in name_lower for k in ["32b", "34b"]):
        gb_per_8k = 2.0
    elif any(k in name_lower for k in ["1b", "0.5b", "tinyllama"]):
        gb_per_8k = 0.15
    elif "3b" in name_lower:
        gb_per_8k = 0.4
    elif any(k in name_lower for k in ["7b", "8b", "9b", "12b", "14b"]):
        gb_per_8k = 1.1
        
    estimated_gb = (context_size / 8192) * gb_per_8k
    return round(estimated_gb, 2)


def free_vram_gb() -> float:
    """Free GPU VRAM in GB (0.0 when no dedicated GPU is detected)."""
    gpu = get_gpu_info()
    free = gpu.get("vram_free_mb") or gpu.get("vram_total_mb") or 0
    return round(free / 1024.0, 2)


# Context ladder used when auto-fitting to VRAM.
_CTX_LADDER = [2048, 4096, 8192, 16384, 32768, 65536, 131072]


def manual_context(model_name: str) -> int:
    """The context window the user set by hand for this model (0 = automatic)."""
    from .config import config
    try:
        return int((config.context_overrides or {}).get(model_name) or 0)
    except (TypeError, ValueError):
        return 0


def recommend_context(model_name: str, hard_cap: int | None = None, manual: bool = True) -> int:
    """Largest sensible context whose model weights + KV cache fit GPU VRAM —
    or, unless `manual` is False, the size the user set for this model.

    Falls back to config.default_context_length when no GPU is detected (on CPU
    the context size doesn't change the GPU/CPU decision). Capped at `hard_cap`
    (the model's true max context) when provided.
    """
    from .config import config
    from .ollama_cloud import is_cloud
    from .target import current
    by_hand = manual_context(model_name) if manual else 0
    if by_hand:
        return min(by_hand, hard_cap) if hard_cap else by_hand
    if is_cloud(model_name):
        # Runs on ollama.com: no local memory limit. A generous window, within
        # the model's own maximum.
        return min(hard_cap or 65536, 65536)
    # The GPU that matters is the one behind the configured Ollama (a server,
    # possibly), not necessarily this computer's.
    target = current()
    vram_gb = target.vram_gb
    cpu_only = vram_gb <= 0
    if cpu_only:
        # No GPU: the KV cache lives in RAM. Use part of it, up to a context
        # that's still quick on a CPU — 2048 can't even hold the tools.
        if target.where != "local" or not target.ram_gb:
            return config.default_context_length
        vram_gb = target.ram_gb * 0.5

    # Weight size of the installed model (GB), if we can find it.
    model_gb = 0.0
    try:
        from .ollama_client import get_local_model_sizes
        sizes = get_local_model_sizes()
        model_gb = sizes.get(model_name) or sizes.get(model_name + ":latest") or 0.0
    except Exception:
        model_gb = 0.0

    headroom = 0.8  # GB reserved for runtime/compute buffers
    cap = hard_cap or _CTX_LADDER[-1]
    if cpu_only:
        cap = min(cap, 8192)
    best = _CTX_LADDER[0]
    for ctx in _CTX_LADDER:
        if ctx > cap:
            break
        need = model_gb + estimate_kv_cache_gb(ctx, model_name) + headroom
        if need <= vram_gb:
            best = ctx
        else:
            break
    if cpu_only:
        return max(min(best, cap), config.default_context_length)
    return min(best, cap)
