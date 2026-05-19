# Changelog

## [0.1.4] - 2026-04-12
### Added
- Browse & Manage Models redesigned: chat/agentic models only (image/video removed)
- Hardware-based filtering: models sorted by best-fit for available RAM/VRAM
- Installed models shown first with green highlight
- Capability badges (🔧 Tool Calling, 💻 Code, 🧠 Reasoning, etc.) on model cards
- Expanded model registry: 55+ models across all major families
- Category filter: Small / Medium / Large / XLarge
- Inline search by name or capability
- Memory system: per-model and global memory with auto-extraction
- Tool-calling agentic system with 6 built-in tools (terminal, file ops, web search, file search)

### Changed
- Full English UI (all commands, help strings, labels)
- OpenCode-inspired purple/violet TUI colour scheme (`#7c3aed`)

## [0.1.3] - 2026-03-26
### Added
- Configurable context length (num_ctx) for models via CLI and config.
- Automated model unloading (keep_alive=0) upon application exit or session end.
- Background threaded workers for TUI chat streaming (no more UI freezing).

### Fixed
- Critical UI-blocking bug in Textual TUI.
- History selection bug when browsing past sessions.
- Consolidated technical debt and improved type hints across all core modules.

All notable changes to this project are documented here.
This project follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/) and
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [1.0.0] – 2025-03-13

### Added
- Persistent interactive TUI shell with arrow-key navigation (powered by `questionary` + `rich`)
- Hardware scanner: GPU (NVIDIA via `nvidia-smi`, AMD via `rocm-smi` / `lspci`, Windows via `wmic`), CPU, RAM, Disk
- Heuristic tokens/sec estimator per model based on detected VRAM
- Live Ollama model list merged with built-in registry at startup
- `get_local_model_sizes()` — model file size displayed in GB for all models (downloaded and not yet downloaded)
- Streaming chat sessions with configurable temperature
- API model stubs: `gpt-4o`, `claude-3-5-sonnet`
- Hardware-aware image generation pipeline (SD v1.5, FLUX-schnell)
- Hardware-aware video generation: LTX Video 2.3 (primary) → SVD (fallback)
- `install.sh` — automated one-shot installer for Linux (detects distro, installs Ollama + deps)
- Built-in model registry with 15 entries covering chat, image, and video models
- `~/.aihub/config.yaml` for persistent user settings (Ollama URL, default model, API keys)
- Windows GPU detection via `wmic` fallback
- Cross-platform file paths via `os.path.join`
- MIT license

### Changed
- Full English UI (all commands, help strings, labels)
- OpenCode-inspired purple/violet TUI colour scheme (`#7c3aed`)

---

## [Unreleased]

- Real OpenAI / Anthropic API integration
- Model search / filtering in TUI browser
- Profile-based configs (work / home)
- Plugin system for custom model backends
