# Changelog

The 0.2.x–0.3.x line is the chat-first Textual TUI rebuild; 0.0.1–0.1.4 below is the
earlier menu-based CLI.

## [0.3.7] - 2026-07-13
### Fixed
- Models downloaded through the Recommended / HuggingFace GGUF tabs were
  invisible afterwards: files landed in `models_download_dir` but the
  Installed tab only listed Ollama models and the currently-loaded
  llama-server model.
### Added
- Installed tab lists all downloaded `.gguf` files (size shown; suspected
  partial downloads flagged red). Enter offers importing the file into
  Ollama (`ollama_client.import_gguf_model`: sha256 blob upload +
  /api/create, with legacy Modelfile fallback) so it becomes a regular
  installed model; `X` deletes the file. Post-download flow routes into the
  same import/use path.

## [0.3.6] - 2026-07-09
### Changed
- Header device counter now follows where the model actually runs: shows a CPU
  counter when Ollama reports the model is CPU-resident, GPU stats otherwise
  (polled from /api/ps every 4 s alongside usage).
- Settings modal redesigned into four tabs (General · Performance · Connections ·
  API Keys) with a detected-GPU info line on the Performance tab. Widget ids and
  save logic unchanged.

## [0.3.5] - 2026-07-09
### Changed
- Removed the duplicate context counter from the bottom footer bar; the top
  header already shows it. Footer right side is now `tok/s · clock`.

## [0.3.4] - 2026-06-12
### Fixed
- AMD GPU detection called `rocm-smi --showvram`, unsupported on newer ROCm; the
  resulting error/usage output leaked to the terminal and corrupted the TUI.
  Switched to `rocm-smi --showmeminfo vram --json` with version-tolerant key
  matching, and silenced stderr on all hardware subprocess calls.
### Added
- Real AMD VRAM size, card model name, and live GPU utilization from rocm-smi
  JSON (previously hardcoded 8 GB with unknown utilization) — feeds the header
  GPU readout, VRAM-fit context, and hardware scan.

## [0.3.3] - 2026-06-12
### Fixed
- Web search: `duckduckgo.com/html/` now returns an empty stub page, so queries
  silently returned no results. Switched to the `html.duckduckgo.com/html/` scrape
  host with a `lite.duckduckgo.com/lite/` fallback, handled the new direct-href
  format (dropped `uddg=` redirect), and filtered sponsored/ad results.

## [0.3.2] - 2026-06-11
### Added
- Tokens/sec counter in the header and footer, colour-coded (green = fast/GPU,
  red = slow/CPU); uses Ollama's `eval_duration` when available, else wall-clock.
### Changed
- Agent sessions auto-fit their context to free VRAM so they stay on the GPU
  instead of forcing a large window that spills to CPU.

## [0.3.1] - 2026-06-11
### Added
- Auto-fit chat context to detected VRAM, with a red warning when a chosen value
  would spill the KV cache to CPU.
- `ollama_num_gpu` force lever in Settings (0 = auto, 999 = force all layers on GPU).
- GPU placement check after the first response (GPU / partial / CPU) via `/api/ps`.

## [0.3.0] - 2026-06-11
### Added
- Reference UI redesign: top header bar, vim-style footer, sidebar with model pill
  and single-key navigation, markdown rendering in the chat log.
- Live token counter, GPU/CPU usage, `CONNECTED`/`OFFLINE` indicator, llmfit-style
  hardware-fit table in the model picker.
- App version shown in the sidebar; global `aihub` command via `install.sh`;
  self-healing `update.sh` for one-command updates.

## [0.2.0] - 2026-06-07
### Added
- Chat-first TUI rebuild on Textual — full-screen chat replaces the menu CLI.
- Cloud API models (Anthropic, OpenAI, Google) alongside local Ollama; optional
  llama.cpp backend.
- Agent mode (plan/build) ported from OpenCode; llmfit-based hardware-fit engine;
  7-tool calling system (terminal, read/write/edit/list files, web search, file search).

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
