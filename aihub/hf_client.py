"""
AIHub - Hugging Face Hub client (v0.1.0).
Fetches available text-generation models from the HF Hub API.
Supports optional Bearer token for private model access.
"""
import requests
from .config import config

# Base HF Hub API endpoint for model search
_HF_API_BASE = "https://huggingface.co/api/models"


def fetch_hf_models(
    token: str = None,
    limit: int = None,
    task: str = "text-generation"
) -> list:
    """
    Fetch popular text-generation models from Hugging Face Hub.

    Args:
        token:  Optional HF API token (overrides config if provided).
        limit:  Max number of models to return (uses config default if None).
        task:   HF pipeline task filter (default: 'text-generation').

    Returns:
        List of model dicts shaped like models_registry.json entries,
        each with a 'source': 'huggingface' field.
        Returns an empty list (not an exception) on any error.
    """
    _token = token or config.hf_api_token
    _limit = limit or config.hf_models_limit

    headers = {}
    if _token:
        headers["Authorization"] = f"Bearer {_token}"

    params = {
        "limit":  _limit,
        "sort":   "downloads",
        "direction": -1,
        "filter": task,
    }

    try:
        response = requests.get(
            _HF_API_BASE,
            headers=headers,
            params=params,
            timeout=8
        )
    except requests.exceptions.ConnectionError:
        return _hf_error("Could not connect to Hugging Face Hub (no internet?).")
    except requests.exceptions.Timeout:
        return _hf_error("Hugging Face Hub request timed out.")

    if response.status_code == 401:
        return _hf_error("Invalid Hugging Face API token. Check hf_api_token in ~/.aihub/config.yaml.")
    if response.status_code == 429:
        return _hf_error("Hugging Face rate limit reached. Set hf_api_token for higher limits.")
    if response.status_code != 200:
        return _hf_error(f"Hugging Face API returned {response.status_code}.")

    try:
        raw_models = response.json()
    except Exception:
        return _hf_error("Could not parse Hugging Face API response.")

    # Shape each raw model into our standard registry format
    shaped = []
    for m in raw_models:
        model_id = m.get("modelId") or m.get("id", "")
        if not model_id:
            continue
        downloads = m.get("downloads", 0)
        shaped.append({
            "name":         model_id,
            "type":         "chat",
            "url":          f"https://huggingface.co/{model_id}",
            "vram_required": 0,   # HF models are API-based by default in registry
            "size_gb":       0,
            "tags":          ["HuggingFace", "API"],
            "description":   f"HF Hub — {downloads:,} downloads",
            "source":        "huggingface",
        })

    return shaped


def _hf_error(message: str) -> list:
    """
    Return a special sentinel list containing a single error-marker entry.
    Callers should check for 'hf_error' key to detect failures.
    """
    return [{"hf_error": message}]


def get_hf_error(models: list) -> str:
    """
    If models list contains an HF error sentinel, return the error message.
    Returns None if the list is clean.
    """
    if models and "hf_error" in models[0]:
        return models[0]["hf_error"]
    return None
