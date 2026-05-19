"""
AIHub - Model registry module (v0.1.4).
Updated schema with capability-based categorization and hardware-aware sorting helpers.
Removes image/video support — chat and agentic models only.
"""
from __future__ import annotations
import json
import os
from .config import config


# ── Capability emoji badges ───────────────────────────────────────────────────
CAPABILITY_BADGES = {
    "tool calling":        "Tool Calling",
    "function calling":    "Func Calls",
    "agents":              "Agents",
    "code":                "Code",
    "reasoning":           "Reasoning",
    "multilingual":        "Multilingual",
    "long context":        "Long Context",
    "rag":                 "RAG",
    "instruction following": "Instruct",
}

# ── Speed category colors / labels ───────────────────────────────────────────
SPEED_COLORS = {
    "very fast": "bold green",
    "fast":      "green",
    "medium":    "yellow",
    "slow":      "red",
}

SPEED_LABELS = {
    "very fast": "Very Fast",
    "fast":      "Fast",
    "medium":    "Medium",
    "slow":      "Slow",
}

# ── Size categories ────────────────────────────────────────────────────────────
CATEGORIES = {
    "small":  {"label": "Small",   "ram_max": 4,   "color": "green"},
    "medium": {"label": "Medium",  "ram_max": 8,   "color": "cyan"},
    "large":  {"label": "Large",   "ram_max": 16,  "color": "yellow"},
    "xlarge": {"label": "XLarge",  "ram_max": 9999, "color": "red"},
}


def load_registry() -> list:
    """Load and return the model registry from the configured JSON file."""
    path = config.models_registry_path
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


def list_models(type_filter: str | None = None) -> list:
    """Return all models; optionally filter by type. Only 'chat' supported in v0.1.4."""
    registry = load_registry()
    # Always exclude image/video models
    registry = [m for m in registry if m.get("type") not in ("image", "video")]
    if type_filter:
        return [m for m in registry if m.get("type") == type_filter]
    return registry


def get_capability_badges(model: dict, max_badges: int = 4) -> list[str]:
    """Return a list of human-readable capability badge strings for a model."""
    caps = model.get("capabilities", [])
    badges = []
    for cap in caps:
        badge = CAPABILITY_BADGES.get(cap.lower())
        if badge and badge not in badges:
            badges.append(badge)
            if len(badges) >= max_badges:
                break
    return badges


def get_speed_label(model: dict) -> str:
    """Return emoji + text speed label for a model."""
    cat = (model.get("speed_category") or "medium").lower()
    return SPEED_LABELS.get(cat, "🔄 Medium")


def get_speed_color(model: dict) -> str:
    """Return Rich color string for a speed category."""
    cat = (model.get("speed_category") or "medium").lower()
    return SPEED_COLORS.get(cat, "yellow")


def get_size_category(model: dict) -> str:
    """Return category key (small/medium/large/xlarge) based on vram_required."""
    vram = float(model.get("vram_required", 0))
    if vram == 0:
        return "small"  # API models
    if vram <= 4:
        return "small"
    if vram <= 8:
        return "medium"
    if vram <= 16:
        return "large"
    return "xlarge"


def categorize_model(name: str, tags: list | None = None) -> str:
    """
    Return a UI category string for a model based on name and tags.
    Used for the legacy CLI 'category' field.
    Categories: Coding, Reasoning, Agentic, General
    """
    name_l = name.lower()
    tags_l = [t.lower() for t in (tags or [])]

    if any(x in name_l for x in ("coder", "starcoder", "codellama", "codeqwen", "deepseek-coder")):
        return "Coding"
    if any("code" in t for t in tags_l):
        return "Coding"

    if any(x in name_l for x in ("deepseek-r1", "phi-4", "phi4", "o1", "reasoning")):
        return "Reasoning"

    if any(x in name_l for x in ("hermes", "command-r", "qwen2.5", "llama3", "mistral-nemo")):
        return "Agentic"
    if any("tool" in t or "agent" in t for t in tags_l):
        return "Agentic"

    return "General"


def sort_models_for_hardware(models: list, hw_ram_gb: float) -> tuple[list, list]:
    """
    Sort models into two groups:
      1. Compatible: vram_required <= hw_ram_gb, sorted descending by vram_required (best-fit first)
      2. Incompatible: vram_required > hw_ram_gb, sorted ascending by vram_required

    API models (vram_required==0) are treated as always compatible.

    Returns (compatible, incompatible)
    """
    api_models = [m for m in models if m.get("vram_required", 0) == 0]
    local_models = [m for m in models if m.get("vram_required", 0) > 0]

    compatible = [m for m in local_models if m.get("vram_required", 0) <= hw_ram_gb]
    incompatible = [m for m in local_models if m.get("vram_required", 0) > hw_ram_gb]

    # Best-fit first: closest to hw limit (descending vram_required)
    compatible.sort(key=lambda m: m.get("vram_required", 0), reverse=True)
    incompatible.sort(key=lambda m: m.get("vram_required", 0))

    # API models always at end of compatible
    compatible = compatible + api_models

    return compatible, incompatible
