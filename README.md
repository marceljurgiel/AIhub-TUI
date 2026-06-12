<div align="center">

# AIHub 🤖

**A chat-first terminal UI for your local AI models.**

AIHub is a full-screen [Textual](https://textual.textualize.io/) TUI for running, managing, and chatting with AI models — **local models through Ollama _and_ cloud API models** (Anthropic, OpenAI, Google) from the same interface. It pairs a fast keyboard-driven chat with hardware-aware model selection, persistent memory, a tool-calling agent mode, and live GPU/throughput readouts — all in the terminal.

[![Python 3.9+](https://img.shields.io/badge/Python-3.9+-blue.svg)](https://www.python.org/)
[![MIT License](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

![AIHub TUI — agent mode running a system-spec check, with live tok/s, context fill, and GPU placement](screenshots/aihub-tui.png)

</div>

## Features

### Chat-First TUI
Running `aihub` opens the full-screen terminal interface:
- **Keyboard-driven** — single-key navigation from the sidebar: `N` New Chat, `A` Agent, `M` Models, `H` History, `E` Memory, `W` Hardware, `S` Settings, `P` Palette, `?` Help.
- **Live status bars** — top header and vim-style footer show the active model, connection state (green `CONNECTED` / red `OFFLINE`), **context fill** (`ctx 1.5k/16k`), **tokens/sec** (colour-coded: green = fast/GPU, red = slow/CPU), and **GPU/CPU usage**.
- **Streaming chat** — token-by-token replies, with `↵` send · `⇧↵` newline · `^R` rerun.
- **Command palette** — `⌘K` / `P` to jump to any action.

### Agent Mode
A tool-calling agent (`A`) with **plan** and **build** sub-modes that can run terminal commands, read/write/edit files, search files, and search the web to complete multi-step tasks:
- **VRAM-aware context** — agent sessions auto-pick the largest context that fits your GPU (capped at the model max), so they stay on the GPU instead of spilling to CPU.
- **Placement check** — after the first response, AIHub reports whether the model loaded on **GPU**, **partial GPU**, or **CPU** (via Ollama's `/api/ps`).
- Tool calls and their output are shown inline in the chat log.

### Hardware Scanner
Automatically detects your system hardware and recommends models that fit:
- **GPU Detection**: NVIDIA (nvidia-smi, GPUtil), AMD (rocm-smi, lspci), Intel, Windows (WMI)
- **CPU Info**: Model, physical/logical cores, clock speed
- **RAM & Disk**: Total, available, usage percentage
- **VRAM-based filtering**: Models ranked by best-fit for your hardware
- **Inference speed estimator**: Heuristic tokens/sec based on detected VRAM

### Model Browser & Registry
- **104 models** in built-in registry (chat, code, reasoning models)
- **Live Ollama integration**: Shows locally installed models
- **Hardware-aware sorting**: Installed models first, then sorted by VRAM fit
- **Capability badges**: Tool Calling, Code, Reasoning, Multilingual, etc.
- **Category filters**: Small / Medium / Large / XLarge

### Cloud API Models
Beyond local Ollama models, AIHub chats with **cloud API models** through the same
interface — local and cloud models sit side by side in the model picker:
- **Anthropic** — Claude Opus 4.8, Sonnet 4.6, Haiku 4.5
- **OpenAI** — GPT-4o, GPT-4o mini, GPT-4 Turbo, o1-mini
- **Google** — Gemini 2.0 Flash, Gemini 1.5 Pro / Flash

Responses stream just like local models, and memory, history, and agent mode all
work with API models too. Add your keys in **Settings** (`S`) → *API keys*, or set
`openai_api_key` / `anthropic_api_key` / `google_api_key` in the config file. No key
is needed for local Ollama models.

### Interactive Chat
- **CLI chat**: Quick chat sessions from command line
- **Streaming responses**: Real-time token-by-token output
- **Configurable context**: Adjustable context window (num_ctx)
- **Temperature control**: Adjust model creativity

### Memory System
AIHub provides a powerful memory system that allows models to "remember" information across sessions.

#### Per-Model Memory
Each model has its own memory file stored at:
```
~/.aihub/memory/<model_name>.md
```
Memory is stored as human-readable Markdown, making it easy to view and edit directly.

#### Global Memory
A shared memory that applies to all models:
```
~/.aihub/memory/global.md
```
Enable in config: `global_memory_enabled: true`

#### How Memory Works
1. **System Prompt Injection**: Memory content is automatically injected as a system prompt at the start of each chat session
2. **Auto-Extraction**: AIHub can automatically summarize and save important information from your current chat session to memory

#### Memory Slash-Commands
During chat, use these commands to manage memory:

| Command | Description |
|---------|-------------|
| `/memory` | View current memory for this model |
| `/memory save <key> <value>` | Save a specific fact manually |
| `/memory clear` | Clear all memory for current model |
| `/memoryadd global` | Auto-extract key facts from chat to **global memory** |
| `/memoryadd chat` | Auto-extract key facts from chat to **model memory** |
| `/history` | Browse and resume past sessions |
| `/tools` | List available agentic tools |
| `/clear` | Clear the current chat context (start fresh) |
| `exit` / `quit` / `q` | End the chat session |

#### How Auto-Extraction Works (`/memoryadd`)
When you use `/memoryadd chat` or `/memoryadd global`:

1. **Collection**: AIHub collects the last 30 messages from your current chat session
2. **Analysis**: It sends these messages to your currently active local Ollama model with a special prompt asking it to extract key facts, user preferences, and important information
3. **Summarization**: The model analyzes the conversation and creates a clean Markdown list of the most important points
4. **Saving**: The extracted facts are saved to either:
   - **Model memory**: `~/.aihub/memory/<model_name>.md` (using `/memoryadd chat`)
   - **Global memory**: `~/.aihub/memory/global.md` (using `/memoryadd global`)
5. **Timestamp**: Each extraction is tagged with a timestamp, so previous memories are preserved

This allows the model to "remember" your preferences, project context, and other important details across future sessions.

#### Manual Memory Management
You can also manually edit memory files directly:
```
~/.aihub/memory/llama3.2:3b.md    # Model-specific memory
~/.aihub/memory/global.md         # Shared global memory
```

#### Memory File Format
```markdown
<!-- AIHub Memory File — model: llama3.2:3b | created: 2026-04-12 -->

## User Preferences
- Prefers concise answers
- Likes code examples

## Project Context
- Working on Python CLI tool
- Using FastAPI framework
```

### Tool-Calling Agentic System
AIHub provides 7 built-in tools for agentic workflows:
- **`run_terminal`**: Execute shell commands (with safety warnings)
- **`read_file` / `write_file` / `edit_file`**: Read, create, and edit files
- **`list_files`**: List directory contents
- **`search_web`**: Search the web via DuckDuckGo (no API key needed)
- **`search_files`**: Glob and grep search across directories

Tools work with Ollama models that support function calling (e.g., llama3.2:3b, qwen2.5:14b).

### History Management
- **Persistent sessions**: Save and resume chat sessions
- **Per-model history**: Organized by model name
- **Configurable limits**: Max saved sessions per model
- **Session browser**: Browse and load past conversations

### Multi-Platform Support
- **Linux**: Full support with all GPU detection methods
- **Windows**: WMI-based GPU detection
- **Cross-platform**: Portable config at `~/.aihub/config.yaml`

---

## The Interface

![AIHub TUI](screenshots/aihub-tui.png)

The screenshot above shows agent mode (`AGENT·BUILD`) running a system-spec check: the
sidebar with single-key navigation, the model pill (`● lfm2.5:8b · CONNECTED · 16K CTX`),
the live header (`28 tok/s · ctx 1.5k/16k · GPU`), inline tool output, the green
`● Running on GPU (100%)` placement line, and the vim-style footer.

### Keyboard Shortcuts

| Key | Action | Key | Action |
|-----|--------|-----|--------|
| `N` | New Chat | `W` | Hardware scan |
| `A` | Agent mode | `S` | Settings |
| `M` | Models browser | `P` / `⌘K` | Command palette |
| `H` | History | `?` | Help |
| `E` | Memory | `↵` / `⇧↵` | Send / newline |
| | | `^R` | Rerun last message |

---

## Installation

### One-liner (Linux / macOS)

```bash
git clone https://github.com/marceljurgiel/AIhub-TUI.git && cd AIhub-TUI && ./install.sh
```

`install.sh` installs any missing system packages (git, python3, venv, pip — via
apt/dnf/pacman/zypper, using `sudo` when not root), creates a local virtualenv
(`.venv`), and installs the app plus the `aihub` command. Then run:

```bash
source .venv/bin/activate && aihub
```

Options: `INSTALL_OLLAMA=1 ./install.sh` also installs the Ollama runtime;
`PYTHON=python3.12 ./install.sh` picks a specific interpreter. Cloud API models
(OpenAI / Anthropic / Google) work without Ollama; local models require it.

### GPU not being used (CPU instead)?

The GPU-vs-CPU decision is made by the **Ollama server**, not aihub. aihub helps
in three ways:

- **Auto-fit context** — the per-chat context length defaults to the largest that
  fits your detected GPU VRAM, and warns (red) if a value you pick will spill the
  KV cache to CPU.
- **Force GPU** — Settings → *Ollama GPU layers (num_gpu)*: `0` = auto,
  `999` = force all layers onto the GPU.
- **Placement check** — after your first message, aihub reports `Running on GPU`,
  `Partial GPU`, or `Running on CPU` (via Ollama's `/api/ps`).

If it still runs on CPU: confirm the **server** can use the GPU (`ollama run <model>`
should use it) and that there's enough free VRAM for the model + context. On AMD
this needs a working ROCm setup on the server (e.g. `HSA_OVERRIDE_GFX_VERSION` for
some cards) — configured where Ollama runs, not in aihub.

### Updating

To pull the latest version any time (force-syncs to the pushed version, even if
`git pull` gets blocked by local edits):

```bash
cd AIhub-TUI && ./update.sh && source .venv/bin/activate && aihub
```

Tip — add a shortcut: `echo "alias aihub-update='cd ~/AIhub-TUI && ./update.sh'" >> ~/.bashrc`,
then just run `aihub-update`. (`update.sh` hard-resets to `origin/main`, so it
discards local edits — intended for a deploy/test box. Requires git auth set up
once via `gh auth login` or a stored token for the private repo.)

### Linux Manual Install

```bash
# Clone the repository
git clone https://github.com/marceljurgiel/AIhub-TUI.git
cd AIhub-TUI

# Create virtual environment (optional but recommended)
python -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Install AIHub
pip install -e .
```

### Windows Installation

#### Prerequisites
1. **Python 3.9+** - Download from https://www.python.org/downloads/
2. **Ollama for Windows** - Download from https://ollama.com/download/windows

#### Steps

```powershell
# Clone the repository
git clone https://github.com/marceljurgiel/AIhub-TUI.git
cd AIhub-TUI

# Create virtual environment
python -m venv venv
venv\Scripts\Activate

# Install dependencies
pip install -r requirements.txt

# Install AIHub
pip install -e .
```

#### Running on Windows

```powershell
# Activate virtual environment
venv\Scripts\Activate

# Run AIHub
aihub
```

Or install globally:

```powershell
# Install globally
pip install -r requirements.txt
pip install -e .

# Run from anywhere
aihub
```

---

## Running AIHub

After installation, simply run:

```bash
aihub
```

With no arguments this launches the **full-screen TUI**. The subcommands below stay
available for quick scripted/CLI use.

### Available Commands

| Command | Description |
|---------|-------------|
| `aihub` | Launch the full-screen TUI |
| `aihub chat` | Start interactive chat session (shows model selector) |
| `aihub chat <model>` | Start chat with specific model |
| `aihub models-list` | List all available models with hardware compatibility |
| `aihub models-download <name>` | Download a model via Ollama |
| `aihub hardware-scan` | Run hardware diagnostics and see recommended models |
| `aihub history <model>` | Browse chat history for a specific model (required) |
| `aihub config` | Show configuration file path and current settings |

### Inside the TUI
Running `aihub` opens the chat screen. From there, use the single-key sidebar
shortcuts (see [Keyboard Shortcuts](#keyboard-shortcuts)) to browse models (`M`),
enter agent mode (`A`), open history (`H`), manage memory (`E`), run a hardware
scan (`W`), or edit settings (`S`). Press `?` for in-app help.

---

## Configuration

AIHub stores config at `~/.aihub/config.yaml`:

```yaml
# Model Settings
ollama_api_url: http://localhost:11434
default_chat_model: qwen:0.5b
default_context_length: 2048      # default num_ctx; chat auto-fits to VRAM
ollama_num_gpu: 0                 # 0 = auto · 999 = force all layers on GPU
models_registry_path: /path/to/models_registry.json

# Cloud API keys (optional — only needed for API models)
openai_api_key: ""
anthropic_api_key: ""
google_api_key: ""

# Agent Mode
agent_min_context: 16384          # min model context to allow agent mode
agent_default_context: 32768      # context agent sessions request (capped to model max)

# Tool Settings
tools_enabled: true
tool_timeout_seconds: 60

# Memory Settings
memory_enabled: true              # inject memory into chat sessions

# History
max_history_sessions: 50
```

> Most settings are editable in-app via **Settings** (`S`) — including the
> *Ollama GPU layers (num_gpu)* lever for forcing GPU usage.

### Data Directories

| Directory | Path |
|-----------|------|
| Config | `~/.aihub/config.yaml` |
| Memory | `~/.aihub/memory/` |
| History | `~/.aihub/history/` |

---

## Tool Calling Usage

To use tools (web search, terminal, file ops), select a model with tool calling capability:

1. Start a chat session with a model that has tool calling capability
2. Ask questions requiring external data

Example:
```
You: What's the latest Python version?
[Model detects need for web search, calls search_web tool]
[Results fed back to model]
Model: The latest Python version is 3.13.0 (released October 2024)
```

---

## Feature Plans: Prebuilt Agents & Skills

*These features are planned for future versions.*

### Prebuilt Agents

#### Plan Agent
An intelligent agent that analyzes complex tasks and creates detailed execution plans. Breaks down goals into manageable steps with clear dependencies.

#### Executor Agent
Takes a pre-made plan and executes it step-by-step. Can call tools, run terminal commands, and interact with files to complete the task.

#### Auto Mode
The most autonomous option - the model:
1. **Plans**: Analyzes the task and creates a plan
2. **Confirms**: Shows you the plan and asks for confirmation
3. **Executes**: Once confirmed, carries out the plan automatically

### Skills System
Reusable prompt templates for common tasks:
- **Code Review**: Analyze code for bugs and improvements
- **Documentation**: Generate documentation from code
- **Refactoring**: Suggest and apply code improvements
- **Testing**: Create test cases for functions
- **Debugging**: Help identify and fix bugs

Skills can be invoked with commands like `/skill review` or `/skill test`.

---

## Future Features

### llama.cpp Backend
Optional `llama-server` (OpenAI-compatible) backend alongside Ollama — already
scaffolded behind `llamacpp_enabled` in config.

---

## Change Log

**Current: 0.3.x — the chat-first TUI rebuild.** AIHub is now a full-screen Textual
interface with agent mode (plan/build), single-key navigation, live tok/s + context +
GPU/CPU readouts, VRAM-aware context fitting, GPU placement checks, and a `num_gpu`
force lever. The table below covers the earlier CLI era (0.0.1 → 0.1.4).

### 0.0.1 (Alpha) → 0.1.4

| Feature | 0.0.1 (Alpha) | 0.1.4 |
|---------|---------------|-------|
| **Model Registry** | ~15 models | **104 models** |
| **Memory System** | Not implemented | **Full** (per-model + global + auto-extract) |
| **Tool-Calling** | Not implemented | **6 tools** (terminal, file ops, web search, file search) |
| **Chat History** | Basic | **Full** with session management and browsing |
| **Hardware Scanner** | Basic GPU detection | **Full** (GPU, CPU, RAM, Disk, VRAM filtering, speed estimation) |
| **Model Categories** | None | **Small/Medium/Large/XLarge** |
| **Capability Badges** | None | **Tool Calling, Code, Reasoning, Multilingual** |
| **Context Length** | Fixed at 2048 | **Configurable** per session |

### What's New in 0.1.4

#### Hardware Scanner
- Complete hardware detection (GPU, CPU, RAM, Disk)
- VRAM-based model filtering and sorting
- Inference speed estimation
- Model recommendations based on your hardware

#### Memory System
- Per-model memory files (`~/.aihub/memory/<model>.md`)
- Global memory shared across models
- AI-powered auto-extraction from conversations
- Slash commands: `/memory`, `/memory save`, `/memory clear`

#### Tool-Calling
- 6 built-in tools for agentic workflows
- Automatic tool execution based on model decisions
- Safety warnings for dangerous commands
- Tool timeout configuration

#### Model Browser
- 104 models in registry
- Category filtering (Small/Medium/Large/XLarge)
- Capability badges display
- Hardware-aware sorting
- Installed models highlighted

#### Chat Improvements
- Configurable context length
- Temperature control
- Streaming responses
- Session persistence

---

## Development

### Project Structure

```
aihub/
├── aihub/
│   ├── cli.py          # Entrypoint — launches the TUI; CLI subcommands
│   ├── config.py       # Configuration loading
│   ├── hardware.py     # Hardware detection + VRAM-fit context
│   ├── fit.py          # llmfit-based hardware recommendations
│   ├── memory.py       # Memory system
│   ├── chat.py         # Chat turn engine (streaming events)
│   ├── agent.py        # Agent mode (plan/build) harness
│   ├── ollama_client.py
│   ├── llamacpp_client.py
│   ├── models.py       # Model registry utilities
│   ├── history.py      # Session management
│   ├── tui/            # Textual TUI
│   │   ├── app.py
│   │   ├── chat_screen.py
│   │   ├── widgets/    # sidebar, status_bar, chat_log, …
│   │   └── modals/     # settings, model_picker, hardware, …
│   └── tools/          # Tool-calling system
│       ├── terminal.py
│       ├── file_ops.py
│       ├── web_search.py
│       └── file_search.py
├── models_registry.json
├── requirements.txt
├── install.sh
└── pyproject.toml
```

### Running Tests

```bash
pytest tests/
```

---

## License

MIT License - See [LICENSE](LICENSE) for details.

---

## Acknowledgments

- [Ollama](https://ollama.com/) - Local AI runtime
- [Questionary](https://questionary.readthedocs.io/) - CLI prompts
- [Rich](https://rich.readthedocs.io/) - Terminal formatting
- [llmfit](https://github.com/AlexsJones/llmfit) (MIT) - the "Recommended" hardware-fit
  engine is a Python port of its approach; the model catalog in
  `aihub/data/llmfit_models.json` is derived from llmfit's database
  (see `aihub/data/LICENSE-llmfit`)
- [OpenCode](https://github.com/sst/opencode) (MIT) - Agent mode's plan/build harness,
  permission model, system prompts, and tool descriptions are ported/adapted from
  OpenCode (see `aihub/data/LICENSE-opencode`)
