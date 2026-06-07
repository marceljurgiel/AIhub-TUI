"""
AIHub — Live model discovery (v0.2.0).

Two discovery functions that never raise — errors are returned as a list
containing {"live_error": "message"} so callers can handle them gracefully.

  fetch_ollama_library()  — Ollama.com model search (undocumented API)
  fetch_hf_gguf_models()  — HuggingFace Hub GGUF model search
"""
from __future__ import annotations

import json
import os
import re
import time
from typing import Any, Dict, List, Optional

import requests


# Community Ollama model list API (JSON; updated regularly)
_OLLAMA_MODELS_URL = "https://ollama-models.zwz.workers.dev/"
_HF_API_BASE       = "https://huggingface.co/api/models"

# Quantisation quality rank — higher = better quality / larger file
_QUANT_RANK: Dict[str, int] = {
    "q2_k":   1, "q3_k_s": 2, "q3_k_m": 3, "q3_k_l":  4,
    "q4_0":   5, "q4_k_s": 6, "q4_k_m": 7,               # Q4_K_M = sweet spot
    "q5_0":   8, "q5_k_s": 9, "q5_k_m": 10,              # Q5_K_M = quality
    "q6_k":  11, "q8_0":  12, "f16":    13, "f32":    14,
    "iq2_xs": 2, "iq2_s":  2, "iq2_m":  3, "iq3_xs": 4,
    "iq3_s":  4, "iq4_xs": 6, "iq4_nl": 6,
}
_RECOMMENDED_QUANT = "q4_k_m"
_QUALITY_QUANT     = "q5_k_m"

# Cache for Ollama library results (avoids hammering the undocumented API)
_ollama_cache: Dict[str, Any] = {}
_CACHE_TTL_SECS = 3600


# ── Ollama library ─────────────────────────────────────────────────────────────

def fetch_ollama_library(query: str = "", limit: int = 50) -> List[Dict[str, Any]]:
    """
    Fetch models from the Ollama library.
    Returns registry-shaped dicts with source="ollama-library".
    Each entry's url = model_name (usable with `ollama pull <name>`).
    """
    cache_key = f"ollama:{query}:{limit}"
    cached = _ollama_cache.get(cache_key)
    if cached and (time.time() - cached["ts"]) < _CACHE_TTL_SECS:
        return cached["data"]

    try:
        resp = requests.get(_OLLAMA_MODELS_URL, timeout=8)
        if not resp.ok:
            return [{"live_error": f"Ollama model list returned {resp.status_code}."}]
        raw = resp.json()
        if not isinstance(raw, list):
            return [{"live_error": "Unexpected response format from Ollama model list."}]
    except requests.exceptions.ConnectionError:
        return [{"live_error": "Cannot reach model list — no internet connection?"}]
    except requests.exceptions.Timeout:
        return [{"live_error": "Ollama model list request timed out."}]
    except Exception as exc:
        return [{"live_error": str(exc)}]

    # Apply query filter client-side
    q = query.lower().strip()
    if q:
        raw = [m for m in raw if q in (m.get("name") or "").lower()
               or q in (m.get("description") or "").lower()]

    result: List[Dict[str, Any]] = []
    for m in raw[:limit]:
        name = m.get("name", "")
        if not name:
            continue
        description = m.get("description") or f"Ollama library — {name}"
        tags = m.get("tags") or []
        result.append({
            "name":          name,
            "type":          "chat",
            "url":           name,              # `ollama pull <name>`
            "size_gb":       0.0,
            "vram_required": 0.0,
            "speed_category": "medium",
            "context_window": 0,
            "capabilities":  ["instruction following"],
            "use_cases":     ["general chat"],
            "tags":          tags,
            "category":      "general",
            "description":   description,
            "source":        "ollama-library",
        })

    _ollama_cache[cache_key] = {"ts": time.time(), "data": result}
    return result


# ── HuggingFace GGUF ──────────────────────────────────────────────────────────

def fetch_hf_gguf_models(
    query: str = "",
    limit: int = 20,
    token: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    Fetch GGUF models from HuggingFace Hub.

    Returns registry-shaped dicts with source="huggingface-gguf" plus an
    extra field:
        gguf_files: list of {filename, size_bytes, size_gb, quant,
                              recommended, quality, download_url}

    url = "https://huggingface.co/<modelId>"
    """
    headers: Dict[str, str] = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    params = {
        "search":    query or "gguf",
        "filter":    "gguf",
        "sort":      "downloads",
        "direction": -1,
        "limit":     limit,
    }
    try:
        resp = requests.get(_HF_API_BASE, headers=headers, params=params, timeout=10)
        if resp.status_code == 401:
            return [{"live_error": "Invalid HuggingFace token — check Settings."}]
        if resp.status_code == 429:
            return [{"live_error": "HuggingFace rate-limited. Set hf_api_token in Settings for higher limits."}]
        if not resp.ok:
            return [{"live_error": f"HuggingFace returned {resp.status_code}."}]
        raw = resp.json()
        if not isinstance(raw, list):
            return [{"live_error": "Unexpected HuggingFace response format."}]
    except requests.exceptions.ConnectionError:
        return [{"live_error": "Cannot reach huggingface.co — no internet connection?"}]
    except requests.exceptions.Timeout:
        return [{"live_error": "HuggingFace request timed out."}]
    except Exception as exc:
        return [{"live_error": str(exc)}]

    result: List[Dict[str, Any]] = []
    for i, m in enumerate(raw):
        model_id = m.get("modelId") or m.get("id", "")
        if not model_id:
            continue
        downloads = m.get("downloads", 0)
        siblings  = m.get("siblings") or []

        # Parse files from search response; detail-fetch only for first 5
        gguf_files = _parse_gguf_siblings(model_id, siblings)
        if not gguf_files and i < 5:
            gguf_files = _fetch_gguf_files(model_id, headers)

        size_gb = _estimate_size(gguf_files)
        result.append({
            "name":          model_id,
            "type":          "chat",
            "url":           f"https://huggingface.co/{model_id}",
            "size_gb":       size_gb,
            "vram_required": size_gb,
            "speed_category": "medium",
            "context_window": 0,
            "capabilities":  ["instruction following"],
            "use_cases":     ["general chat"],
            "tags":          ["HuggingFace", "GGUF"],
            "category":      "general",
            "description":   f"HF Hub GGUF · {downloads:,} downloads",
            "source":        "huggingface-gguf",
            "gguf_files":    gguf_files,            # extra — not in registry schema
        })

    return result


def fetch_hf_gguf_files(model_id: str, token: Optional[str] = None) -> List[Dict[str, Any]]:
    """Fetch the full GGUF file list for a specific HuggingFace model ID."""
    headers: Dict[str, str] = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return _fetch_gguf_files(model_id, headers)


def _fetch_gguf_files(model_id: str, headers: Dict[str, str]) -> List[Dict[str, Any]]:
    try:
        r = requests.get(f"{_HF_API_BASE}/{model_id}", headers=headers, timeout=6)
        if not r.ok:
            return []
        siblings = r.json().get("siblings") or []
        return _parse_gguf_siblings(model_id, siblings)
    except Exception:
        return []


_QUANT_RE = re.compile(
    r"[_\-](q\d+_k_[sml]|q\d+_[0-9]|q\d+_k|iq\d+_[a-z]+|f16|f32|bf16)",
    re.IGNORECASE,
)


def _parse_gguf_siblings(
    model_id: str,
    siblings: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """
    Extract .gguf files from a siblings list.
    Annotate each with quant, size, recommended/quality flags, and download URL.
    """
    files: List[Dict[str, Any]] = []
    for s in siblings:
        fname = s.get("rfilename", "")
        if not fname.lower().endswith(".gguf"):
            continue
        size_bytes = s.get("size") or 0
        size_gb    = round(size_bytes / 1024 ** 3, 2) if size_bytes else 0.0

        m = _QUANT_RE.search(fname)
        quant = m.group(1).lower() if m else "unknown"

        files.append({
            "filename":     fname,
            "size_bytes":   size_bytes,
            "size_gb":      size_gb,
            "quant":        quant,
            "recommended":  quant == _RECOMMENDED_QUANT,
            "quality":      quant == _QUALITY_QUANT,
            "download_url": f"https://huggingface.co/{model_id}/resolve/main/{fname}",
        })

    # Sort: recommended first, then by quality rank descending, then by size
    files.sort(key=lambda f: (
        0 if f["recommended"] else (1 if f["quality"] else 2),
        -_QUANT_RANK.get(f["quant"], 0),
    ))
    return files


def _estimate_size(gguf_files: List[Dict[str, Any]]) -> float:
    for f in gguf_files:
        if f.get("recommended") and f.get("size_gb"):
            return f["size_gb"]
    if gguf_files and gguf_files[0].get("size_gb"):
        return gguf_files[0]["size_gb"]
    return 0.0


# ── Utility ───────────────────────────────────────────────────────────────────

def get_live_error(models: List[Dict[str, Any]]) -> Optional[str]:
    """Return error string if the list contains a live_error sentinel, else None."""
    if models and "live_error" in models[0]:
        return models[0]["live_error"]
    return None
