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
        response.raise_for_status()
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
    Fetch detailed information about a model from Ollama, including context length.
    Returns a dict with 'context_length' and other potential metadata.
    """
    url     = f"{config.ollama_api_url}/api/show"
    payload = {"name": model_name}
    try:
        response = requests.post(url, json=payload, timeout=5)
        response.raise_for_status()
        data = response.json()

        # Parse context length from parameters or modelfile
        params = data.get("parameters", "")
        # Common pattern: num_ctx 4096
        ctx_match = re.search(r"num_ctx\s+(\d+)", params)
        if ctx_match:
            return {"context_length": int(ctx_match.group(1))}

        # If not in params, check modelfile or fallback to config default
        return {"context_length": config.default_context_length}
    except Exception:
        return {"context_length": config.default_context_length}


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
