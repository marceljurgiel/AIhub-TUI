"""
AIHub — live model catalogs (Ollama library + Hugging Face GGUF).

Both are cached on disk (~/.aihub/cache) and refreshed in the background on
every app start (`refresh()`); readers get the cache instantly
(stale-while-revalidate), so the model picker never waits on the network.

Ollama: parsed from https://ollama.com/library (name, description,
capability badges, size variants, pulls, last update), plus each popular
model's /tags page for the real download size of every variant. The old
community mirror missed Gemma 4, gpt-oss, Qwen 3.5–3.8 and more.

Hugging Face: the most-downloaded text-generation GGUF repos from trusted
publishers (raw trending is mostly "uncensored" fine-tunes and non-chat
models), with parameter counts from the API's gguf metadata.
"""
from __future__ import annotations

import html
import json
import logging
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, List, Optional

import requests

from .config import CONFIG_DIR

log = logging.getLogger(__name__)

OLLAMA_LIBRARY_URL = "https://ollama.com/library?sort=popular"
OLLAMA_TAGS_URL = "https://ollama.com/library/{name}/tags"
HF_API_URL = "https://huggingface.co/api/models"

TRUSTED_HF = {
    "unsloth", "bartowski", "lmstudio-community", "ggml-org", "Qwen", "google",
    "microsoft", "mistralai", "LiquidAI", "ibm-granite", "meta-llama",
}

TAGS_TTL_SECS = 7 * 24 * 3600      # variant sizes rarely change
TAGS_TOP_N = 70                    # tags pages fetched for the most popular models
_CAPABILITY_BADGES = {"tools", "thinking", "vision", "embedding", "audio", "cloud"}
_SIZE_TAG = re.compile(r"^(e?)(\d+(?:\.\d+)?)([mbMB])(?:-a(\d+(?:\.\d+)?)b)?$")


def _cache_path(name: str) -> str:
    return os.path.join(CONFIG_DIR, "cache", f"catalog_{name}.json")


def _read_cache(name: str) -> Dict[str, Any]:
    try:
        with open(_cache_path(name), encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except FileNotFoundError:
        return {}
    except Exception:
        log.warning("catalog cache %s unreadable — refetching", name, exc_info=True)
        return {}


def _write_cache(name: str, data: Dict[str, Any]) -> None:
    path = _cache_path(name)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
    os.replace(tmp, path)


# ── Parsing ───────────────────────────────────────────────────────────────────

def parse_size_tag(tag: str) -> Optional[Dict[str, float]]:
    """'8b' → {params_b: 8}; '270m' → 0.27; 'e4b' → effective 4B (Gemma 'E'
    models); '26b-a4b' → 26B total, 4B active (MoE)."""
    m = _SIZE_TAG.match(tag.strip())
    if not m:
        return None
    effective, num, unit, active = m.groups()
    params = float(num) / (1000.0 if unit.lower() == "m" else 1.0)
    out = {"params_b": params}
    if active:
        out["active_b"] = float(active)
    if effective:
        out["effective"] = 1.0
    return out


def _pulls(text: str) -> int:
    m = re.match(r"([\d.,]+)\s*([KMB]?)", text.strip())
    if not m:
        return 0
    n = float(m.group(1).replace(",", ""))
    return int(n * {"": 1, "K": 1e3, "M": 1e6, "B": 1e9}[m.group(2)])


def parse_library(page: str) -> List[Dict[str, Any]]:
    """Model cards from ollama.com/library HTML."""
    models = []
    seen = set()
    for chunk in page.split('href="/library/')[1:]:
        name = chunk.split('"', 1)[0]
        if not name or "/" in name or name in seen:
            continue
        body = chunk[:6000]
        desc = re.search(r'<p class="[^"]*break-words[^"]*">([^<]*)</p>', body)
        badges = [html.unescape(b).strip() for b in re.findall(r'rounded-md[^"]*">([^<]+)</span>', body)]
        text = re.sub(r"\s+", " ", re.sub(r"<[^>]+>|&nbsp;", " ", body))
        pulls = re.search(r"([\d.,]+[KMB]?)\s*Pulls", text)
        updated = re.search(r"Updated\s*([\w ]+? ago)", text)
        seen.add(name)
        models.append({
            "name": name,
            "description": html.unescape(desc.group(1)).strip() if desc else "",
            "capabilities": [b for b in badges if b in _CAPABILITY_BADGES],
            "sizes": [b for b in badges if parse_size_tag(b)],
            "pulls": _pulls(pulls.group(1)) if pulls else 0,
            "updated": updated.group(1) if updated else "",
        })
    return models


def parse_tags(page: str, name: str) -> Dict[str, Dict[str, Any]]:
    """Per-variant download size (GB, lower bound of the range) and context
    from a /library/<name>/tags page."""
    text = re.sub(r"\s+", " ", re.sub(r"<[^>]+>|&nbsp;", " ", page))
    out: Dict[str, Dict[str, Any]] = {}
    pat = re.compile(rf"{re.escape(name)}:([\w.\-]+)(?: latest)? [0-9a-f]{{12}} • "
                     r"([\d.]+)\s*([GMK]B)(?: - [\d.]+\s*[GMK]B)? • ([\d.]+[KM]) context")
    for tag, size, unit, ctx in pat.findall(text):
        if tag in out:
            continue
        gb = float(size) / {"GB": 1.0, "MB": 1024.0, "KB": 1024.0 ** 2}[unit]
        ctx_n = int(float(ctx[:-1]) * (1024 if ctx.endswith("K") else 1024 ** 2))
        out[tag] = {"size_gb": round(gb, 2), "context": ctx_n}
    return out


# ── Fetching ─────────────────────────────────────────────────────────────────

def _get(url: str, **kw) -> requests.Response:
    r = requests.get(url, timeout=kw.pop("timeout", 15), headers={"User-Agent": "aihub"}, **kw)
    r.raise_for_status()
    return r


def refresh_ollama(force: bool = False) -> Dict[str, Any]:
    """Fetch the library (always) and the tags pages of the most popular
    models whose sizes are missing, stale, or whose model was updated."""
    old = _read_cache("ollama")
    old_models = {m["name"]: m for m in old.get("models", [])}
    models = parse_library(_get(OLLAMA_LIBRARY_URL).text)
    now = time.time()

    def needs_tags(m):
        prev = old_models.get(m["name"], {})
        fresh = now - prev.get("tags_fetched_at", 0) < TAGS_TTL_SECS
        # Freshness is about when we fetched, not what we found: a page that
        # yielded no sizes must not be refetched on every start.
        return force or "tags_fetched_at" not in prev or not fresh or prev.get("updated") != m["updated"]

    chat = [m for m in models if "embedding" not in m["capabilities"]]
    todo = [m for m in chat[:TAGS_TOP_N] if needs_tags(m)]

    def fetch(m):
        try:
            return m["name"], parse_tags(_get(OLLAMA_TAGS_URL.format(name=m["name"])).text, m["name"])
        except Exception as exc:
            log.info("tags for %s failed: %s", m["name"], exc)
            return m["name"], None

    fetched = {}
    with ThreadPoolExecutor(max_workers=4) as pool:
        for name, variants in pool.map(fetch, todo):
            if variants is not None:
                fetched[name] = variants
    for m in models:
        if m["name"] in fetched:
            m["variants"], m["tags_fetched_at"] = fetched[m["name"]], now
        elif m["name"] in old_models:
            prev = old_models[m["name"]]
            m["variants"] = prev.get("variants", {})
            m["tags_fetched_at"] = prev.get("tags_fetched_at", 0)
    data = {"fetched_at": now, "models": models}
    _write_cache("ollama", data)
    return data


def refresh_hf(token: Optional[str] = None) -> Dict[str, Any]:
    params = [
        ("filter", "gguf"), ("pipeline_tag", "text-generation"), ("sort", "downloads"),
        ("direction", "-1"), ("limit", "300"), ("expand[]", "gguf"),
        ("expand[]", "downloads"), ("expand[]", "lastModified"), ("expand[]", "author"),
    ]
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    r = requests.get(HF_API_URL, params=params, headers=headers, timeout=20)
    r.raise_for_status()
    models = []
    for m in r.json():
        if m.get("author") not in TRUSTED_HF:
            continue
        g = m.get("gguf") or {}
        total = g.get("total") or 0
        active = re.search(r"[-_]A(\d+(?:\.\d+)?)B", m.get("id", ""), re.IGNORECASE)
        models.append({
            "id": m["id"],
            "author": m.get("author", ""),
            "architecture": g.get("architecture", ""),
            "params_b": round(total / 1e9, 2) if total else 0.0,
            "active_b": float(active.group(1)) if active else None,
            "downloads": m.get("downloads", 0),
            "updated": (m.get("lastModified") or "")[:10],
        })
    data = {"fetched_at": time.time(), "models": models}
    _write_cache("hf", data)
    return data


def refresh(force: bool = False) -> Dict[str, Any]:
    """Refresh both catalogs; one failing doesn't stop the other. Returns
    {ollama: {count, age_s} | {error}, hf: …}."""
    from .config import config
    out: Dict[str, Any] = {}
    for name, fn in (("ollama", lambda: refresh_ollama(force)),
                     ("hf", lambda: refresh_hf(config.hf_api_token or None))):
        try:
            data = fn()
            out[name] = {"count": len(data["models"]), "age_s": 0}
        except Exception as exc:
            log.warning("catalog %s refresh failed: %s", name, exc)
            cached = _read_cache(name)
            out[name] = {"error": str(exc), "count": len(cached.get("models", [])),
                         "age_s": _age(cached)}
    return out


def _age(data: Dict[str, Any]) -> Optional[int]:
    ts = data.get("fetched_at")
    return int(time.time() - ts) if ts else None


def ollama_models() -> Dict[str, Any]:
    data = _read_cache("ollama")
    return {"models": data.get("models", []), "age_s": _age(data)}


def hf_models() -> Dict[str, Any]:
    data = _read_cache("hf")
    return {"models": data.get("models", []), "age_s": _age(data)}
