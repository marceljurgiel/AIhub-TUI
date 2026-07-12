"""
AIHub - Ollama API client (v0.1.0).
Handles all communication with the local Ollama REST API.
v0.1.0: Added 'tools' parameter support to chat_stream() for tool-calling models.
"""
import json
import requests
import re
from typing import List, Dict, Any, Optional, Generator

from .config import config


def is_ollama_running() -> bool:
    """Return True if the Ollama server is reachable."""
    try:
        response = requests.get(config.ollama_api_url, timeout=2)
        return response.status_code == 200
    except requests.exceptions.RequestException:
        return False


def get_local_models() -> list:
    """Return a list of model name strings currently installed in Ollama."""
    try:
        response = requests.get(f"{config.ollama_api_url}/api/tags", timeout=3)
        response.raise_for_status()
        return [m["name"] for m in response.json().get("models", [])]
    except Exception:
        return []


def import_gguf_model(path: str, model_name: str) -> tuple:
    """Import a local .gguf file into Ollama as `model_name`, making it a
    regular installed model (shows up in /api/tags like any pulled model).

    Modern servers: upload the file as a blob (sha256), then /api/create with
    a files map. Older servers: fall back to a Modelfile 'FROM <path>' create
    (works when the server runs on this machine). Returns (ok, error).
    """
    import hashlib
    import os as _os
    try:
        # 1. Digest of the file (Ollama addresses blobs by sha256).
        h = hashlib.sha256()
        with open(path, "rb") as fh:
            for chunk in iter(lambda: fh.read(1024 * 1024), b""):
                h.update(chunk)
        digest = f"sha256:{h.hexdigest()}"

        # 2. Ensure the blob exists server-side (HEAD then upload).
        blob_url = f"{config.ollama_api_url}/api/blobs/{digest}"
        try:
            have = requests.head(blob_url, timeout=10).status_code == 200
        except Exception:
            have = False
        if not have:
            with open(path, "rb") as fh:
                up = requests.post(blob_url, data=fh, timeout=3600)
            if up.status_code not in (200, 201):
                return False, f"blob upload failed: HTTP {up.status_code}"

        # 3. Create the model from the blob.
        resp = requests.post(
            f"{config.ollama_api_url}/api/create",
            json={"model": model_name,
                  "files": {_os.path.basename(path): digest},
                  "stream": False},
            timeout=600,
        )
        if resp.ok and '"error"' not in resp.text:
            return True, ""

        # 4. Legacy fallback (pre-0.6 servers; same-machine path).
        legacy = requests.post(
            f"{config.ollama_api_url}/api/create",
            json={"name": model_name, "modelfile": f"FROM {path}",
                  "stream": False},
            timeout=600,
        )
        if legacy.ok and '"error"' not in legacy.text:
            return True, ""
        try:
            reason = resp.json().get("error") or resp.text
        except Exception:
            reason = resp.text
        return False, str(reason)[:300]
    except Exception as exc:
        return False, str(exc)


def get_local_model_sizes() -> dict:
    """
    Return a dict mapping model name → size in GB for installed models.
    Falls back to an empty dict if Ollama is offline.
    """
    try:
        response = requests.get(f"{config.ollama_api_url}/api/tags", timeout=3)
        response.raise_for_status()
        result = {}
        for m in response.json().get("models", []):
            size_bytes = m.get("size", 0)
            result[m["name"]] = round(size_bytes / (1024 ** 3), 2)
        return result
    except Exception:
        return {}


def pull_model_stream(model_name: str):
    """
    Pull (download) a model from Ollama and yield progress dicts.

    Each yielded dict may contain keys: 'status', 'completed', 'total', 'error'.
    """
    url     = f"{config.ollama_api_url}/api/pull"
    payload = {"name": model_name}
    try:
        response = requests.post(url, json=payload, stream=True, timeout=600)
        response.raise_for_status()
        for line in response.iter_lines():
            if line:
                yield json.loads(line)
    except Exception as exc:
        yield {"error": str(exc)}


def chat_stream(model_name: str, messages: List[Dict[str, Any]], temperature: float = 0.7, tools: Optional[List[Dict[str, Any]]] = None, context_length: Optional[int] = None) -> Generator[Dict[str, Any], None, None]:
    """
    Send messages to Ollama and yield streamed response chunks.

    Args:
        model_name:     Ollama model identifier.
        messages:       List of message dicts (role/content).
        temperature:    Sampling temperature.
        tools:          Optional list of tool schemas.
        context_length: Optional context window size override.
    """
    url     = f"{config.ollama_api_url}/api/chat"
    options = {
        "temperature": temperature,
        "num_ctx":     context_length or config.default_context_length
    }
    # Force GPU layer offload when configured. Only send when > 0 — num_gpu=0
    # would force Ollama to run on CPU.
    if getattr(config, "ollama_num_gpu", 0) and config.ollama_num_gpu > 0:
        options["num_gpu"] = config.ollama_num_gpu
    payload = {
        "model":    model_name,
        "messages": messages,
        "stream":   True,
        "options":  options
    }
    if tools:
        payload["tools"] = tools

    try:
        response = requests.post(url, json=payload, stream=True, timeout=120)
        if not response.ok:
            # Surface the Ollama error body so callers get a useful message.
            try:
                body = response.json()
                reason = body.get("error") or body.get("message") or response.text
            except Exception:
                reason = response.text or response.reason
            yield {"error": f"{response.status_code}: {reason}"}
            return
        for line in response.iter_lines():
            if line:
                yield json.loads(line)
    except Exception as exc:
        yield {"error": str(exc)}


def chat_sync(model_name: str, messages: List[Dict[str, Any]], temperature: float = 0.7, context_length: Optional[int] = None) -> str:
    """Send messages to Ollama and return the full response string (non-streaming)."""
    url     = f"{config.ollama_api_url}/api/chat"
    options = {
        "temperature": temperature,
        "num_ctx":     context_length or config.default_context_length
    }
    payload = {
        "model":    model_name,
        "messages": messages,
        "stream":   False,
        "options":  options
    }
    try:
        response = requests.post(url, json=payload, timeout=120)
        response.raise_for_status()
        return response.json().get("message", {}).get("content", "")
    except Exception:
        return "Error: Could not generate a response."


def get_model_info(model_name: str) -> dict:
    """
    Fetch model details from Ollama `/api/show`.

    Returns a dict with:
      context_length:  configured num_ctx if set, else the model's max
      max_context:     the model's true maximum context window (from model_info)
      capabilities:    list, e.g. ["completion", "tools", "vision"]
      supports_tools:  bool — whether tool calling is supported
    """
    url     = f"{config.ollama_api_url}/api/show"
    payload = {"name": model_name}
    try:
        response = requests.post(url, json=payload, timeout=5)
        response.raise_for_status()
        data = response.json()

        capabilities = data.get("capabilities") or []

        # True max context from model_info: "<arch>.context_length"
        max_context = 0
        model_info = data.get("model_info") or {}
        for k, v in model_info.items():
            if k.endswith(".context_length"):
                try:
                    max_context = int(v)
                except (TypeError, ValueError):
                    pass
                break

        # Configured num_ctx, if pinned in the modelfile parameters
        params = data.get("parameters", "")
        ctx_match = re.search(r"num_ctx\s+(\d+)", params)
        configured = int(ctx_match.group(1)) if ctx_match else 0

        context_length = configured or max_context or config.default_context_length
        return {
            "context_length": context_length,
            "max_context":    max_context or context_length,
            "capabilities":   capabilities,
            "supports_tools": "tools" in capabilities,
        }
    except Exception:
        return {
            "context_length": config.default_context_length,
            "max_context":    config.default_context_length,
            "capabilities":   [],
            "supports_tools": False,
        }


def unload_model(model_name: str):
    """
    Tell Ollama to immediately unload a model from RAM/VRAM.
    Uses keep_alive=0 via /api/chat to trigger de-loading.
    """
    url     = f"{config.ollama_api_url}/api/chat"
    payload = {
        "model":      model_name,
        "messages":   [],
        "keep_alive": 0
    }
    try:
        requests.post(url, json=payload, timeout=5)
    except Exception:
        pass


def get_running_models() -> list:
    """Return Ollama's currently-loaded models (GET /api/ps). Each entry has
    'name', 'size' (total bytes) and 'size_vram' (bytes resident on GPU)."""
    try:
        response = requests.get(f"{config.ollama_api_url}/api/ps", timeout=3)
        response.raise_for_status()
        return response.json().get("models", []) or []
    except Exception:
        return []


def model_placement(model_name: str) -> dict:
    """Where is `model_name` running? Returns
        {"size", "size_vram", "gpu_fraction"}  (gpu_fraction in 0..1)
    or {} when the model isn't currently loaded."""
    for m in get_running_models():
        name = m.get("name") or m.get("model") or ""
        # Match on the loaded name or its bare stem (Ollama may add ':latest').
        if name == model_name or name.split(":")[0] == model_name.split(":")[0]:
            size = float(m.get("size", 0) or 0)
            vram = float(m.get("size_vram", 0) or 0)
            frac = (vram / size) if size else 0.0
            return {"size": size, "size_vram": vram, "gpu_fraction": frac}
    return {}
