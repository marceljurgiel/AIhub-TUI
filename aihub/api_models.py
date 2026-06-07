"""
AIHub — Cloud API model catalog (v0.2.0).

Curated list of API-based models (OpenAI, Anthropic, Google). These run via
api_client.py rather than a local runtime. Each entry is registry-shaped with
source="api" plus a `provider` and `api_model` field.
"""
from __future__ import annotations

from typing import Any, Dict, List

from .config import config


# (provider, api_model_id, display_name, context_window, description)
_CATALOG = [
    # ── Anthropic ────────────────────────────────────────────────────────
    ("anthropic", "claude-opus-4-8",   "Claude Opus 4.8",   1_000_000, "Most capable — agentic, coding, reasoning"),
    ("anthropic", "claude-sonnet-4-6", "Claude Sonnet 4.6", 1_000_000, "Best balance of speed and intelligence"),
    ("anthropic", "claude-haiku-4-5",  "Claude Haiku 4.5",    200_000, "Fastest, most cost-effective"),
    # ── OpenAI ───────────────────────────────────────────────────────────
    ("openai", "gpt-4o",        "GPT-4o",        128_000, "OpenAI flagship multimodal"),
    ("openai", "gpt-4o-mini",   "GPT-4o mini",   128_000, "Fast, low-cost OpenAI model"),
    ("openai", "gpt-4-turbo",   "GPT-4 Turbo",   128_000, "Previous-gen flagship"),
    ("openai", "o1-mini",       "o1-mini",       128_000, "Reasoning model (mini)"),
    # ── Google ───────────────────────────────────────────────────────────
    ("google", "gemini-2.0-flash",     "Gemini 2.0 Flash",      1_000_000, "Fast Google multimodal"),
    ("google", "gemini-1.5-pro",       "Gemini 1.5 Pro",        2_000_000, "Large-context Google model"),
    ("google", "gemini-1.5-flash",     "Gemini 1.5 Flash",      1_000_000, "Fast, cost-effective Gemini"),
]

_PROVIDER_LABEL = {
    "anthropic": "Anthropic",
    "openai":    "OpenAI",
    "google":    "Google",
}


def _key_configured(provider: str) -> bool:
    if provider == "anthropic":
        return bool(config.anthropic_api_key.strip())
    if provider == "openai":
        return bool(config.openai_api_key.strip())
    if provider == "google":
        return bool(config.google_api_key.strip())
    return False


def get_api_models() -> List[Dict[str, Any]]:
    """Return registry-shaped dicts for all API models, annotated with whether
    the provider's key is configured."""
    out: List[Dict[str, Any]] = []
    for provider, api_model, display, ctx, desc in _CATALOG:
        out.append({
            "name":          f"{_PROVIDER_LABEL[provider]} · {display}",
            "type":          "chat",
            "url":           f"api://{provider}/{api_model}",
            "size_gb":       0.0,
            "vram_required": 0.0,
            "speed_category": "api",
            "context_window": ctx,
            "capabilities":  ["instruction following", "tool calling"],
            "use_cases":     ["general chat", "coding", "reasoning"],
            "tags":          [_PROVIDER_LABEL[provider], "API"],
            "category":      "api",
            "description":   desc,
            "source":        "api",
            # API-specific extras
            "provider":      provider,
            "api_model":     api_model,
            "key_ready":     _key_configured(provider),
        })
    return out


def provider_key_status() -> Dict[str, bool]:
    """Map provider → whether its key is configured."""
    return {p: _key_configured(p) for p in _PROVIDER_LABEL}


def resolve_api_url(model_name: str) -> str:
    """
    Given a bare API model id (e.g. 'claude-opus-4-8'), return its api:// url,
    or "" if it is not a known API model. Used to recover the backend when
    resuming a saved session that predates backend persistence.
    """
    for provider, api_model, *_ in _CATALOG:
        if api_model == model_name:
            return f"api://{provider}/{api_model}"
    return ""
