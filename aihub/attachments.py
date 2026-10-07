"""
AIHub — image attachments for vision models.

An attached image is normalised once (Pillow: at most MAX_SIDE px on the long
side, JPEG — PNG when it has transparency) and stored content-addressed in
~/.aihub/attachments/<id>. Chat messages, the UI and saved history carry only
the id:

    {"role": "user", "content": "what is this?", "images": ["3f2a9c1b7e04.jpg"]}

Right before a request, `expand` swaps ids for the image data
({"mime", "data"} base64), and each backend writes it in its own format
(Ollama `images`, OpenAI `image_url`, Anthropic/Google content blocks).
"""
from __future__ import annotations

import base64
import hashlib
import io
import logging
import os
import re
import shutil
import subprocess
import sys
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import unquote, urlparse

from .config import CONFIG_DIR

log = logging.getLogger(__name__)

MAX_SIDE = 1568            # long side, px — what vision models actually use
MAX_INPUT_BYTES = 20 * 1024 * 1024
IMAGE_EXT = (".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".tif", ".tiff", ".heic")
_ID = re.compile(r"^[0-9a-f]{12}\.(jpg|png)$")


def att_dir() -> str:
    return os.path.join(CONFIG_DIR, "attachments")


# ── Adding ───────────────────────────────────────────────────────────────────

def add_bytes(data: bytes, name: str = "image") -> Dict[str, Any]:
    """Normalise and store one image; returns {id, name, width, height, kb}."""
    from PIL import Image, ImageOps

    if len(data) > MAX_INPUT_BYTES:
        raise ValueError(f"{name}: {len(data) // 1024 // 1024} MB — images up to 20 MB")
    try:
        img = Image.open(io.BytesIO(data))
        img.load()
    except Exception:
        raise ValueError(f"{name} isn't an image AIhub can read")
    img = ImageOps.exif_transpose(img)                 # phone photos: upright
    if getattr(img, "n_frames", 1) > 1:
        img.seek(0)                                    # animated → first frame
    if max(img.size) > MAX_SIDE:
        img.thumbnail((MAX_SIDE, MAX_SIDE), Image.LANCZOS)
    alpha = img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info)
    out = io.BytesIO()
    if alpha:
        img.convert("RGBA").save(out, "PNG", optimize=True)
        ext = "png"
    else:
        img.convert("RGB").save(out, "JPEG", quality=85, optimize=True)
        ext = "jpg"
    blob = out.getvalue()
    att_id = f"{hashlib.sha256(blob).hexdigest()[:12]}.{ext}"
    os.makedirs(att_dir(), exist_ok=True)
    path = os.path.join(att_dir(), att_id)
    if not os.path.exists(path):
        with open(path + ".tmp", "wb") as f:
            f.write(blob)
        os.replace(path + ".tmp", path)
    return {"id": att_id, "name": name, "width": img.size[0], "height": img.size[1],
            "kb": max(1, round(len(blob) / 1024))}


def clean_path(text: str) -> str:
    """A dropped or pasted path → filesystem path: quotes, file:// URIs
    (percent-encoded), ~, backslash-escaped spaces."""
    t = (text or "").strip().strip("'\"")
    if t.startswith("file://"):
        t = unquote(urlparse(t).path)
        if re.match(r"^/[A-Za-z]:/", t):          # file:///C:/Users/… on Windows
            t = t[1:]
    t = t.replace("\\ ", " ")
    return os.path.expanduser(t)


def looks_like_image_path(text: str) -> bool:
    p = clean_path(text)
    return p.lower().endswith(IMAGE_EXT) and os.path.isfile(p)


def add_file(path: str) -> Dict[str, Any]:
    p = clean_path(path)
    if not os.path.isfile(p):
        raise FileNotFoundError(f"no such file: {p}")
    if os.path.getsize(p) > MAX_INPUT_BYTES:
        raise ValueError(f"{os.path.basename(p)}: larger than 20 MB")
    with open(p, "rb") as f:
        return add_bytes(f.read(), os.path.basename(p))


def _run(cmd: List[str]) -> Optional[bytes]:
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=5)
        return r.stdout if r.returncode == 0 else None
    except Exception:
        return None


_PS_IMAGE = ("Add-Type -AssemblyName System.Windows.Forms; "
             "$i = [System.Windows.Forms.Clipboard]::GetImage(); "
             "if ($i) { $i.Save($args[0], [System.Drawing.Imaging.ImageFormat]::Png); 'ok' }")


def clipboard_image_type() -> Optional[Tuple[str, str]]:
    """(tool, mime) when the clipboard holds an image, else None."""
    if sys.platform == "win32":
        out = _run(["powershell", "-NoProfile", "-STA", "-Command",
                    "Add-Type -AssemblyName System.Windows.Forms; [System.Windows.Forms.Clipboard]::ContainsImage()"])
        return ("powershell", "image/png") if out and out.strip().lower() == b"true" else None
    if os.environ.get("WAYLAND_DISPLAY") and shutil.which("wl-paste"):
        types = (_run(["wl-paste", "--list-types"]) or b"").decode(errors="ignore").split()
        img = next((t for t in types if t.startswith("image/")), None)
        if img:
            return "wl-paste", img
    if os.environ.get("DISPLAY") and shutil.which("xclip"):
        targets = (_run(["xclip", "-selection", "clipboard", "-t", "TARGETS", "-o"]) or b"").decode(errors="ignore").split()
        img = next((t for t in targets if t.startswith("image/")), None)
        if img:
            return "xclip", img
    return None


def add_clipboard() -> Dict[str, Any]:
    found = clipboard_image_type()
    if not found:
        raise ValueError("the clipboard has no image (copy a screenshot or an image first)")
    tool, mime = found
    if tool == "powershell":
        import tempfile
        tmp = os.path.join(tempfile.gettempdir(), "aihub-clipboard.png")
        _run(["powershell", "-NoProfile", "-STA", "-Command", _PS_IMAGE.replace("$args[0]", f"'{tmp}'")])
        try:
            with open(tmp, "rb") as f:
                data = f.read()
        finally:
            try:
                os.remove(tmp)
            except OSError:
                pass
        return add_bytes(data, "clipboard.png")
    cmd = (["wl-paste", "--type", mime] if tool == "wl-paste"
           else ["xclip", "-selection", "clipboard", "-t", mime, "-o"])
    data = _run(cmd)
    if not data:
        raise RuntimeError(f"reading the image from the clipboard failed ({tool})")
    return add_bytes(data, f"clipboard.{mime.split('/')[-1]}")


# ── Sending ──────────────────────────────────────────────────────────────────

def load(att_id: str) -> Optional[Dict[str, str]]:
    """{mime, data(base64)} for an id, or None when it's gone."""
    if not _ID.match(att_id or ""):
        return None
    path = os.path.join(att_dir(), att_id)
    try:
        with open(path, "rb") as f:
            data = base64.b64encode(f.read()).decode()
    except FileNotFoundError:
        return None
    return {"mime": "image/png" if att_id.endswith(".png") else "image/jpeg", "data": data}


def has_images(message: Dict[str, Any]) -> bool:
    return message.get("role") == "user" and bool(message.get("images"))


def expand(messages: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], Dict[int, Dict[str, Any]]]:
    """A copy of `messages` with user image ids replaced by {mime, data}, and
    a map id(expanded) → original message, so the caller can hand the UI back
    messages that carry ids (never megabytes of base64)."""
    out, originals = [], {}
    for m in messages:
        if not has_images(m) or not all(isinstance(i, str) for i in m["images"]):
            out.append(m)
            continue
        imgs, missing = [], 0
        for att in m["images"]:
            loaded = load(att)
            if loaded:
                imgs.append(loaded)
            else:
                missing += 1
        new = {**m, "images": imgs}
        if missing:
            new["content"] = (m.get("content") or "") + "\n[image no longer available]" * missing
        if not imgs:
            new.pop("images")
        originals[id(new)] = m
        out.append(new)
    return out, originals


def restore(messages: List[Dict[str, Any]], originals: Dict[int, Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [originals.get(id(m), m) for m in messages]


def image_data(message: Dict[str, Any]) -> List[Dict[str, str]]:
    """The expanded {mime, data} images of a message (empty if none)."""
    return [i for i in (message.get("images") or []) if isinstance(i, dict) and i.get("data")]


# ── Which models can see ─────────────────────────────────────────────────────

_VISION_CACHE: Dict[str, bool] = {}


def supports_vision(model: str, backend: str = "ollama") -> bool:
    if backend == "api":
        from .api_models import get_api_models
        entry = next((m for m in get_api_models()
                      if model in (m.get("api_model"), m.get("url"), m.get("name"))), None)
        return bool(entry and entry.get("vision"))
    if backend != "ollama":
        return False                        # llama.cpp: depends on its mmproj, unknown
    if model not in _VISION_CACHE:
        from .ollama_client import get_model_info
        info = get_model_info(model)
        if not info.get("capabilities"):
            return False                    # couldn't ask: don't cache a guess
        _VISION_CACHE[model] = "vision" in info["capabilities"]
    return _VISION_CACHE[model]


def vision_models(installed: List[str]) -> List[str]:
    return [m for m in installed if supports_vision(m)]
