"""
AIHub - Configuration module.
Loads and persists user settings from ~/.aihub/config.yaml.
v0.1.0: Added fields for Hugging Face token, tools toggle, memory/history dirs.
"""
import os
import yaml
from pydantic import BaseModel, Field


CONFIG_DIR  = os.path.expanduser(os.path.join("~", ".aihub"))
CONFIG_FILE = os.path.join(CONFIG_DIR, "config.yaml")

# Derived data directories (not user-configurable, computed from CONFIG_DIR)
MEMORY_DIR  = os.path.join(CONFIG_DIR, "memory")
HISTORY_DIR = os.path.join(CONFIG_DIR, "history")

# Default registry path — works on both Windows and Linux
_PACKAGE_ROOT     = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_REGISTRY_DEFAULT = os.path.join(_PACKAGE_ROOT, "models_registry.json")


class AppConfig(BaseModel):
    """Application configuration model."""
    models_registry_path: str = Field(default=_REGISTRY_DEFAULT)
    default_chat_model:   str = Field(default="qwen:0.5b")
    ollama_api_url:       str = Field(default="http://localhost:11434")
    openai_api_key:       str = Field(default="")
    anthropic_api_key:    str = Field(default="")
    google_api_key:       str = Field(default="", description="Google Gemini API key")

    # v0.1.0 — Hugging Face integration
    hf_api_token:         str = Field(default="", description="Hugging Face API token for fetching models")
    hf_models_limit:      int = Field(default=20, description="Number of HF models to display in browser")

    # v0.1.0 — Agentic tools
    tools_enabled:        bool = Field(default=True, description="Enable the tool-calling agentic system")
    tool_timeout_seconds: int  = Field(default=60,   description="Timeout for terminal tool execution")

    # v0.1.0 — History
    max_history_sessions: int = Field(default=50, description="Max saved sessions per model")

    # v0.1.1 — Memory and Hardware
    memory_enabled: bool = Field(default=True, description="Inject shared memory into chat sessions")
    hardware_scan_completed: bool = Field(default=False, description="Whether the initial hardware scan was completed")
    # v0.1.2 — Context Length
    default_context_length: int = Field(default=2048, description="Default context window size (num_ctx) for models")

    # v0.2.0 — llama.cpp backend
    llamacpp_url:          str  = Field(default="http://localhost:8080",     description="Base URL of a running llama-server (OpenAI-compatible)")
    llamacpp_enabled:      bool = Field(default=False,                        description="Show llama.cpp as an available backend in the TUI")

    # v0.2.0 — Live model discovery
    ollama_library_limit:  int  = Field(default=50,                           description="Max models fetched from Ollama library live search")
    hf_gguf_limit:         int  = Field(default=20,                           description="Max GGUF model entries fetched from HuggingFace")
    models_download_dir:   str  = Field(default=os.path.join(os.path.expanduser("~"), ".aihub", "models"),
                                        description="Directory where downloaded GGUF files are saved")

    # v0.3.0 — Agent mode (OpenCode-style plan/build harness)
    agent_min_context:     int  = Field(default=16384, description="Minimum model context window required to enter agent mode")
    agent_default_context: int  = Field(default=32768, description="Context window agent sessions request (capped to the model max)")
    llamacpp_agent_allow:  bool = Field(default=False, description="Allow llama.cpp models in agent mode (tool support is model-dependent)")
    project_dir:           str  = Field(default="",    description="Working directory for agent file/shell tools (empty = current dir)")
    recent_models:         list = Field(default_factory=list, description="Recently used model names, most-recent first")


def load_config() -> AppConfig:
    """Load config from disk, falling back to defaults if not present or invalid."""
    cfg = AppConfig()
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
            cfg = AppConfig(**data)
        except Exception:
            pass

    # Force models_registry_path to point to the current package's registry
    # to prevent version upgrades from getting stuck on an older path in config.yaml
    cfg.models_registry_path = _REGISTRY_DEFAULT
    return cfg


def save_config(cfg: AppConfig) -> None:
    """Persist config to disk, creating the directory if necessary."""
    os.makedirs(CONFIG_DIR, exist_ok=True)
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        yaml.dump(cfg.model_dump(), f, default_flow_style=False, allow_unicode=True)


config = load_config()
