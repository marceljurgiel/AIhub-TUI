"""Small helpers the install scripts (install.sh / install.ps1) call, so both
platforms share one implementation:

    python -m aihub.installer version
    python -m aihub.installer server            print the configured Ollama URL
    python -m aihub.installer server URL        save URL as the Ollama server
    python -m aihub.installer check URL         exit 0 when Ollama answers there
    python -m aihub.installer start             start a local, installed Ollama
    python -m aihub.installer models URL        number of models on that server
    python -m aihub.installer has URL MODEL     exit 0 when MODEL is on that server
    python -m aihub.installer pull URL MODEL    download MODEL there, with progress
"""
from __future__ import annotations

import json
import sys

import requests


def normalize(url: str) -> str:
    url = url.strip().rstrip("/")
    if "://" not in url:
        url = "http://" + url
    host = url.split("://", 1)[1]
    if ":" not in host.split("/", 1)[0]:
        url += ":11434"
    return url


def check(url: str) -> bool:
    try:
        return "version" in requests.get(f"{url}/api/version", timeout=4).json()
    except Exception:
        return False


def models(url: str) -> int:
    try:
        return len(requests.get(f"{url}/api/tags", timeout=6).json().get("models") or [])
    except Exception:
        return 0


def has(url: str, name: str) -> bool:
    try:
        names = [m["name"] for m in requests.get(f"{url}/api/tags", timeout=6).json().get("models") or []]
    except Exception:
        return False
    return name in names or f"{name}:latest" in names


def pull(url: str, name: str) -> None:
    last = ""
    with requests.post(f"{url}/api/pull", json={"model": name}, stream=True, timeout=None) as r:
        if not r.ok:
            raise SystemExit(f"could not download {name}: {r.text.strip()}")
        for line in r.iter_lines():
            d = json.loads(line or "{}")
            if d.get("error"):
                from .ollama_client import pull_error
                raise SystemExit(f"could not download {name}: {pull_error(name, d['error'], base_url=url)}")
            status = d.get("status", "")
            if d.get("total"):
                status += f" {d.get('completed', 0) * 100 // d['total']}%"
            if status != last:
                print(f"\r  {status:<60}", end="", flush=True)
                last = status
    print()


def main(argv: list[str]) -> int:
    cmd, args = (argv[0], argv[1:]) if argv else ("", [])
    if cmd == "version":
        from . import __version__
        print(__version__)
    elif cmd == "server" and not args:
        from .config import config
        print(config.ollama_api_url)
    elif cmd == "server":
        from .config import config, save_config
        config.ollama_api_url = normalize(args[0])
        save_config(config)
        print(config.ollama_api_url)
    elif cmd == "check":
        return 0 if check(normalize(args[0])) else 1
    elif cmd == "start":
        from .ollama_client import start_local_ollama
        return 0 if start_local_ollama() else 1
    elif cmd == "models":
        print(models(normalize(args[0])))
    elif cmd == "has":
        return 0 if has(normalize(args[0]), args[1]) else 1
    elif cmd == "pull":
        pull(normalize(args[0]), args[1])
    else:
        print(__doc__)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
