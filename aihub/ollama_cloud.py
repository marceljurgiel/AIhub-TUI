"""
AIHub — Ollama Cloud models.

Ollama runs some open models in its own cloud: tags ending in "cloud"
("gpt-oss:120b-cloud", "kimi-k2.6:cloud"). A signed-in Ollama server
forwards them like local models — no download, nothing on the GPU. The
free plan covers only some of them, with hourly/weekly limits; others need
paid credits, and Ollama retires old ones (the tag then errors).

Whether a model is free can't be read from any API, so it is probed once
(a one-token chat through the configured server) and cached per server in
~/.aihub/cache/cloud_access.json for a few days.
"""
from __future__ import annotations

import json
import logging
import os
import re
import time
from typing import Any, Dict, List, Optional

import requests

from .config import CONFIG_DIR

log = logging.getLogger(__name__)

TAGS_URL = "https://ollama.com/library/{name}/tags"
STATUS_TTL = 3 * 24 * 3600
TAGS_TTL = 24 * 3600


def is_cloud(model: str) -> bool:
    """'gpt-oss:120b-cloud', 'kimi-k2.6:cloud' — runs on ollama.com."""
    tag = (model or "").split(":", 1)[1] if ":" in (model or "") else ""
    return tag == "cloud" or tag.endswith("-cloud")


# ── Friendly errors ─────────────────────────────────────────────────────────

def explain(error: str, model: str = "") -> Optional[str]:
    """A plain-language version of an Ollama Cloud error, or None."""
    e = error or ""
    name = model or "this model"
    if "not included in your free usage" in e:
        return (f"{name} isn't in Ollama's free cloud plan — it needs paid credits "
                "(ollama.com/settings). Free cloud models are marked 'free' in ^O → Cloud.")
    m = re.search(r"was retired at (\d{4}-\d{2}-\d{2})", e)
    if m or "retired" in e:
        when = f" on {m.group(1)}" if m else ""
        return (f"Ollama retired {name}{when} — it no longer runs. Pick another model "
                f"(^O → Cloud) and remove the old tag on the server: ollama rm {name}")
    if re.search(r"(?i)usage limit|rate limit|too many requests|\b429\b|quota", e):
        return ("Ollama Cloud usage limit reached (the free plan has hourly and weekly "
                "limits) — try again later, use a local model, or add credits at ollama.com.")
    if re.search(r"(?i)unauthori[sz]ed|\b401\b|sign ?in|not signed", e):
        return ("The Ollama server isn't signed in to ollama.com, so cloud models can't run. "
                "On the server run: ollama signin")
    return None


# ── Catalog of cloud tags ───────────────────────────────────────────────────

def _cache_path(name: str) -> str:
    return os.path.join(CONFIG_DIR, "cache", name)


def _read(name: str) -> Dict[str, Any]:
    try:
        with open(_cache_path(name), encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except FileNotFoundError:
        return {}
    except Exception:
        log.warning("%s unreadable — starting fresh", name, exc_info=True)
        return {}


def _write(name: str, data: Dict[str, Any]) -> None:
    path = _cache_path(name)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=1)
    os.replace(tmp, path)


def parse_cloud_tags(page: str, name: str) -> List[str]:
    return sorted(set(re.findall(rf"{re.escape(name)}:[a-z0-9._-]*cloud\b", page)))


def cloud_tags(force: bool = False) -> List[Dict[str, Any]]:
    """Every cloud tag in the Ollama library (cached a day): one row per tag
    with the library model's description, capabilities and update time."""
    from . import catalog
    cache = _read("cloud_tags.json")
    if not force and time.time() - cache.get("fetched_at", 0) < TAGS_TTL and cache.get("tags"):
        return cache["tags"]
    rows = []
    for m in catalog.ollama_models()["models"]:
        if "cloud" not in (m.get("capabilities") or []):
            continue
        try:
            page = requests.get(TAGS_URL.format(name=m["name"]), headers={"User-Agent": "aihub"},
                                timeout=15).text
        except Exception as exc:
            log.info("cloud tags for %s failed: %s", m["name"], exc)
            continue
        for tag in parse_cloud_tags(page, m["name"]):
            rows.append({
                "name": tag, "family": m["name"], "description": m.get("description", ""),
                "capabilities": [c for c in m.get("capabilities", []) if c != "cloud"],
                "updated": m.get("updated", ""), "pulls": m.get("pulls", 0),
            })
    if rows:
        _write("cloud_tags.json", {"fetched_at": time.time(), "tags": rows})
    return rows or cache.get("tags", [])


# ── Free / paid / retired, per server ───────────────────────────────────────

def _status_key() -> str:
    from .config import config
    return config.ollama_api_url


def statuses() -> Dict[str, Dict[str, Any]]:
    return _read("cloud_access.json").get(_status_key(), {})


def classify(error: str) -> str:
    if "not included in your free usage" in error:
        return "paid"
    if "retired" in error:
        return "retired"
    if re.search(r"(?i)unauthori[sz]ed|\b401\b|sign ?in", error):
        return "signin"
    if re.search(r"(?i)usage limit|rate limit|too many requests|\b429\b", error):
        return "limit"
    if re.search(r"(?i)not found", error):
        return "missing"
    return "error"


def probe(tag: str, timeout: float = 60) -> Dict[str, Any]:
    """One-token chat through the configured server; remembers the result."""
    from .config import config
    try:
        r = requests.post(f"{config.ollama_api_url}/api/chat", timeout=timeout, json={
            "model": tag, "stream": False,
            "messages": [{"role": "user", "content": "Reply with: ok"}],
            "options": {"num_predict": 1}})
        body = r.json() if r.content else {}
        status = "free" if "message" in body else classify(str(body.get("error") or r.text))
        detail = "" if status == "free" else str(body.get("error") or "")[:200]
    except Exception as exc:
        status, detail = "error", str(exc)[:200]
    data = _read("cloud_access.json")
    # A usage limit says nothing about the plan: keep what we knew.
    if status != "limit" or tag not in data.get(_status_key(), {}):
        data.setdefault(_status_key(), {})[tag] = {"status": status, "detail": detail, "at": int(time.time())}
        _write("cloud_access.json", data)
    return {"name": tag, "status": status, "detail": detail}


def record_error(tag: str, error: str) -> None:
    """A chat that failed with a plan/retired error teaches the same thing a probe would."""
    status = classify(error)
    if status in ("paid", "retired"):
        data = _read("cloud_access.json")
        data.setdefault(_status_key(), {})[tag] = {"status": status, "detail": error[:200], "at": int(time.time())}
        _write("cloud_access.json", data)


def listing(installed: Optional[List[str]] = None) -> List[Dict[str, Any]]:
    """Cloud tags from the library plus any installed on the server (even
    retired ones), each with its known status ('' = not probed yet, or the
    probe is older than STATUS_TTL)."""
    known = statuses()
    rows = {r["name"]: dict(r) for r in cloud_tags()}
    for name in installed or []:
        if is_cloud(name) and name not in rows:
            rows[name] = {"name": name, "family": name.split(":")[0], "description": "",
                          "capabilities": [], "updated": "", "pulls": 0}
    now = time.time()
    order = {"free": 0, "": 1, "limit": 1, "error": 2, "signin": 2, "paid": 3, "missing": 4, "retired": 5}
    out = []
    for r in rows.values():
        st = known.get(r["name"], {})
        fresh = now - st.get("at", 0) < STATUS_TTL
        r["status"] = st.get("status", "") if fresh or st.get("status") == "retired" else ""
        r["installed"] = r["name"] in (installed or [])
        out.append(r)
    out.sort(key=lambda r: (order.get(r["status"], 2), r["family"], r["name"]))
    return out
