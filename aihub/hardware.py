"""
AIHub - Hardware detection module.
Collects full device specs: GPU, CPU, RAM, Disk, OS.
Used to rank models by hardware compatibility and estimate inference speed.
"""
import platform
import shutil
import subprocess
from typing import Any, Dict

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


def get_gpu_info() -> Dict[str, Any]:
    """
    Detect GPU vendor, model, and VRAM.
    Tries GPUtil, then NVIDIA (nvidia-smi), then AMD (rocm-smi), then lspci fallback.
    On Windows falls back to wmi if neither tool is available.
    """
    # ── NVIDIA (GPUtil) ──────────────────────────────────────────────────────
    try:
        import GPUtil
        gpus = GPUtil.getGPUs()
        if gpus:
            gpu = gpus[0]
            return {
                "vendor":       "NVIDIA",
                "model":        gpu.name,
                "vram_total_mb": int(gpu.memoryTotal),
                "vram_free_mb":  int(gpu.memoryFree),
            }
    except ImportError:
        pass

    # ── NVIDIA ──────────────────────────────────────────────────────────────
    if shutil.which("nvidia-smi"):
        try:
            out = subprocess.check_output(
                "nvidia-smi --query-gpu=name,memory.total,memory.free --format=csv,noheader",
                shell=True, text=True
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
    if shutil.which("rocm-smi"):
        try:
            subprocess.check_output("rocm-smi --showid --showvram", shell=True, text=True)
            return {
                "vendor":       "AMD",
                "model":        "AMD Radeon GPU (via rocm-smi)",
                "vram_total_mb": 8192,
                "vram_free_mb":  8192,
            }
        except Exception:
            pass

    # ── Windows: wmi ─────────────────────────────────────────────────────────
    if platform.system() == "Windows":
        try:
            import wmi
            w = wmi.WMI()
            for controller in w.Win32_VideoController():
                try:
                    vram_bytes = int(controller.AdapterRAM) if controller.AdapterRAM else 0
                except:
                    vram_bytes = 0
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
            out = subprocess.check_output("lspci", shell=True, text=True).lower()
            if "amd" in out or "radeon" in out:
                return {"vendor": "AMD",    "model": "AMD Radeon (PCI)", "vram_total_mb": 8192, "vram_free_mb": 8192}
            if "nvidia" in out:
                return {"vendor": "NVIDIA", "model": "NVIDIA GPU (PCI)", "vram_total_mb": 8192, "vram_free_mb": 8192}
            if "intel" in out:
                return {"vendor": "Intel",  "model": "Intel Integrated",  "vram_total_mb": 0,    "vram_free_mb": 0}
        except Exception:
            pass

    return {
        "vendor":       "Unknown",
        "model":        "No dedicated GPU detected",
        "vram_total_mb": 0,
        "vram_free_mb":  0,
    }


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
    Heuristic: ~1GB per 8192 tokens for standard 7B-9B models.
    """
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
