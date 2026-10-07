"""
AIHub — reusable HuggingFace GGUF downloads (Xet-aware).

Extracted from tui/modals/gguf_picker.py so any front-end (the Textual TUI,
the OpenTUI bridge, the CLI) can download a GGUF file with progress reporting
via a plain callback instead of a Textual-specific `call_from_thread`.

HuggingFace's plain-HTTP CAS bridge 403s on large `resolve/…` files
(huggingface/xet-core#592). The `huggingface_hub` client speaks the Xet
protocol and is the reliable path; a raw streaming GET is kept as a fallback
for environments where `huggingface_hub` isn't installed.
"""
from __future__ import annotations

import logging
import os
import threading
from typing import Callable, Optional

from .config import config

log = logging.getLogger(__name__)

# progress_cb(pct: int, done_bytes: int, total_bytes: int) -> None
ProgressCb = Optional[Callable[[int, int, int], None]]


def hf_download(
    repo_id: str,
    filename: str,
    dest: str,
    token: Optional[str] = None,
    size_bytes: int = 0,
    progress_cb: ProgressCb = None,
) -> str:
    """Download `filename` from `repo_id` to `dest`, reporting progress.

    Returns the destination path on success; raises on failure.
    """
    os.makedirs(os.path.dirname(dest) or config.models_download_dir, exist_ok=True)
    try:
        from huggingface_hub import hf_hub_download  # noqa: F401
        have_hub = True
    except ImportError:
        have_hub = False

    if have_hub:
        return _hub_download(repo_id, filename, dest, token, size_bytes, progress_cb)
    return _raw_download(repo_id, filename, dest, token, progress_cb)


def _hub_download(
    repo_id: str,
    filename: str,
    dest: str,
    token: Optional[str],
    size_bytes: int,
    progress_cb: ProgressCb,
) -> str:
    """Blocking download via huggingface_hub, with a size-poller thread feeding
    `progress_cb` (hf_hub has no native progress callback)."""
    from huggingface_hub import hf_hub_download
    try:
        # hf_hub's own tqdm bars would corrupt a TUI; our poller drives progress.
        from huggingface_hub.utils import disable_progress_bars
        disable_progress_bars()
    except Exception:
        pass

    local_dir = os.path.dirname(dest) or config.models_download_dir
    total = size_bytes or 0
    stop = threading.Event()

    def poll() -> None:
        cache = os.path.join(local_dir, ".cache", "huggingface")
        while not stop.wait(0.5):
            size = 0
            try:
                for root, _dirs, names in os.walk(cache):
                    for n in names:
                        if n.endswith(".incomplete"):
                            size = max(size, os.path.getsize(os.path.join(root, n)))
            except Exception:
                pass
            try:
                if os.path.exists(dest):
                    size = max(size, os.path.getsize(dest))
            except Exception:
                pass
            if progress_cb:
                pct = min(100, int(size / total * 100)) if total else 0
                try:
                    progress_cb(pct, size, total)
                except Exception:
                    log.warning("download progress callback failed; progress stops", exc_info=True)
                    return

    t = threading.Thread(target=poll, daemon=True)
    t.start()
    try:
        hf_hub_download(
            repo_id=repo_id,
            filename=filename,
            local_dir=local_dir,
            token=token or None,
        )
    finally:
        stop.set()
        t.join(timeout=2)
    if progress_cb:
        try:
            progress_cb(100, total, total)
        except Exception:
            log.warning("download progress callback failed", exc_info=True)
    return dest


def _raw_download(
    repo_id: str,
    filename: str,
    dest: str,
    token: Optional[str],
    progress_cb: ProgressCb,
) -> str:
    """Fallback: raw streaming GET (used only when huggingface_hub is absent)."""
    import requests

    url = f"https://huggingface.co/{repo_id}/resolve/main/{filename}"
    headers = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    resp = requests.get(url, stream=True, timeout=600, headers=headers)
    resp.raise_for_status()
    total = int(resp.headers.get("content-length", 0))
    done = 0
    with open(dest, "wb") as fh:
        for chunk in resp.iter_content(chunk_size=1024 * 256):
            if chunk:
                fh.write(chunk)
                done += len(chunk)
                if progress_cb and total:
                    progress_cb(min(100, int(done / total * 100)), done, total)
    return dest


def friendly_error(err: str) -> str:
    """Add an HF-token hint to 401/403 download failures."""
    if "403" in err or "401" in err:
        return (f"{err[:160]}\n"
                "HF blocks some anonymous downloads — add a free HuggingFace "
                "token in Settings → API Keys and retry.")
    return err[:300]
