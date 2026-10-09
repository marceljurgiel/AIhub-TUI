"""
AIhub — is there a newer Ollama than the one AIhub talks to?

New models often need a new Ollama (the registry answers an old one with
412). At start the app asks `check()`: the server's version, Ollama's latest
release (GitHub, cached a day), and how to update — by AIhub itself when
Ollama runs on this machine (Linux installer, Homebrew), or a command to run
on the other machine when it doesn't.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import time
from typing import Any, Dict
from urllib.parse import urlparse

import requests

from .config import CONFIG_DIR, config
from .target import is_local

LATEST_URL = "https://api.github.com/repos/ollama/ollama/releases/latest"
INSTALL_COMMAND = "curl -fsSL https://ollama.com/install.sh | sh"
DAY = 24 * 3600


def _parts(v: str):
    """'v0.41.0-rc1' → ((0, 41, 0), False): numbers, then whether it's final."""
    m = re.match(r"v?(\d+)\.(\d+)\.(\d+)(.*)$", (v or "").strip())
    if not m:
        return (0, 0, 0), True
    return tuple(int(x) for x in m.groups()[:3]), not m.group(4)


def is_newer(a: str, b: str) -> bool:
    """Is version `a` newer than `b`? A release candidate of a higher
    version counts as newer; of the same version, it doesn't."""
    (na, fa), (nb, fb) = _parts(a), _parts(b)
    return na > nb or (na == nb and fa and not fb)


def _cache_path() -> str:
    return os.path.join(CONFIG_DIR, "cache", "ollama-latest.json")


def latest() -> str:
    """Ollama's latest release, asked of GitHub at most once a day."""
    try:
        with open(_cache_path(), encoding="utf-8") as f:
            d = json.load(f)
        if time.time() - float(d.get("checked", 0)) < DAY and d.get("version"):
            return str(d["version"])
    except (OSError, ValueError):
        pass
    try:
        r = requests.get(LATEST_URL, timeout=6, headers={"Accept": "application/vnd.github+json"})
        r.raise_for_status()
        version = str(r.json().get("tag_name") or "").lstrip("v")
    except Exception:
        return ""
    if version:
        os.makedirs(os.path.dirname(_cache_path()), exist_ok=True)
        with open(_cache_path(), "w", encoding="utf-8") as f:
            json.dump({"version": version, "checked": time.time()}, f)
    return version


def _server_version(url: str) -> str:
    try:
        r = requests.get(f"{url}/api/version", timeout=5)
        r.raise_for_status()
        return str(r.json().get("version") or "")
    except Exception:
        return ""


def _platform() -> str:
    return sys.platform


def _brew_has_ollama() -> bool:
    if not shutil.which("brew"):
        return False
    try:
        return subprocess.run(["brew", "list", "--versions", "ollama"], capture_output=True,
                              timeout=15).returncode == 0
    except Exception:
        return False


def check() -> Dict[str, Any]:
    """{server, latest, newer, local, host, how, command}.
    how: "installer" (Linux, this machine: AIhub runs it), "brew" (macOS,
    this machine: AIhub runs it), "app" (Ollama's own app updates itself),
    "manual" (another machine: run `command` there)."""
    url = config.ollama_api_url
    server, newest = _server_version(url), latest()
    local = is_local(url)
    how, command = "manual", INSTALL_COMMAND
    if local:
        plat = _platform()
        if plat.startswith("linux"):
            how = "installer"
        elif plat == "darwin":
            how, command = ("brew", "brew upgrade ollama") if _brew_has_ollama() else ("app", "")
        else:
            how, command = "app", ""
    return {
        "server": server,
        "latest": newest,
        "newer": bool(server and newest and is_newer(newest, server)),
        "local": local,
        "host": urlparse(url).hostname or "",
        "how": how,
        "command": command,
    }
