<div align="center">

# AIHub 🤖

**Your all-in-one local AI management platform.**

AIHub is a unified interface for managing, browsing, and chatting with local AI models. It provides hardware-aware model selection, persistent memory, and a tool-calling agentic system.

> **Note:** API integration (OpenAI, Anthropic, Google) is currently in development and not available in this version.

[![Python 3.9+](https://img.shields.io/badge/Python-3.9+-blue.svg)](https://www.python.org/)
[![MIT License](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

</div>

## Features

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
AIHub provides 6 built-in tools for agentic workflows:
- **Terminal**: Execute shell commands (with safety warnings)
- **File Operations**: Read, write, list files
- **Web Search**: Search the web via DuckDuckGo (no API key needed)
- **File Search**: Glob and grep search across directories

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

## Screenshots

### Main Menu
The main entry point to AIHub with all available options.

![Main Menu](/screenshots/Main_menu.png)

### Model Browser
Browse, filter, and manage available models with hardware compatibility.

![Browse & Manage Models](/screenshots/Browse_and_manage_models.png)
![Model Selection](/screenshots/Model_selection_menu.png)
![Model Details](/screenshots/Model_chat_details.png)

### Model Download
Download new models directly from Ollama registry.

![Model Download](/screenshots/model_download_pull.png)

### Hardware Scanner
Automatic hardware detection with model recommendations.

![Hardware Diagnostics](/screenshots/Hardware_Diagnostics.png)

### Memory System
AI-powered memory system that allows models to remember information.

![Memory Basic](/screenshots/memory_working_example.png)
![Memory Feature](/screenshots/memory_feature_working_example.png)
![Memory Auto-Extract](/screenshots/memory_add_auto_extraxt_working_example.png)
![Memory Clear](/screenshots/memory_clear.png)
![Memory Settings](/screenshots/Memory_managment_settings_menu.png)

### Chat History
Browse and resume past conversations.

![History List](/screenshots/chat_history_current_model_list.png)
![History View](/screenshots/model_chat_history_view.png)

### Configuration
View and edit AIHub settings.

![Configuration](/screenshots/Confuguration_windows_menu.png)

---

## Installation

### Linux Quick Install

```bash
git clone https://github.com/marceljurgiel/AIhub.git
cd AIhub
./install.sh
```

The installer will:
1. Detect your Linux distribution
2. Install Ollama (if not present)
3. Install Python dependencies
4. Install AIHub system-wide

### Linux Manual Install

```bash
# Clone the repository
git clone https://github.com/marceljurgiel/AIhub.git
cd AIhub

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
git clone https://github.com/marceljurgiel/AIhub.git
cd AIhub

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

### Available Commands

| Command | Description |
|---------|-------------|
| `aihub` | Launch main interactive menu |
| `aihub chat` | Start interactive chat session (shows model selector) |
| `aihub chat <model>` | Start chat with specific model |
| `aihub models-list` | List all available models with hardware compatibility |
| `aihub models-download <name>` | Download a model via Ollama |
| `aihub hardware-scan` | Run hardware diagnostics and see recommended models |
| `aihub history <model>` | Browse chat history for a specific model (required) |
| `aihub config` | Show configuration file path and current settings |

### Interactive Menu Options
When running `aihub`, you'll see an interactive menu with:
1. **Browse & Manage Models** - View, filter, and download models
2. **Start Chat** - Begin a new chat session
3. **Chat History** - Resume past conversations
4. **Memory Management** - View/edit memory for models
5. **Hardware Scan** - View system diagnostics
6. **Configuration** - Edit settings
7. **Exit** - Close the application

---

## Configuration

AIHub stores config at `~/.aihub/config.yaml`:

```yaml
# Model Settings
ollama_api_url: http://localhost:11434
default_chat_model: llama3.2:3b
default_context_length: 2048
models_registry_path: /path/to/models_registry.json

# Tool Settings
tools_enabled: true
tool_timeout_seconds: 60

# Memory Settings
global_memory_enabled: false

# History
max_history_sessions: 50
```

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

### API Integration (In Development)
- **OpenAI**: GPT-4o, GPT-4o-mini, GPT-4 Turbo
- **Anthropic**: Claude 3.5 Sonnet, Claude 3 Haiku
- **Google**: Gemini 1.5 Pro, Gemini 1.5 Flash
- Unified model selection across all providers

### TUI Interface Alternative
A full-screen Textual-based TUI interface with:
- Rich panels and tables
- Keyboard navigation
- Mouse support
- Smooth animations
- Alternative to the CLI menu-based interface

---

## Change Log: 0.0.1 (Alpha) → 0.1.4

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
│   ├── cli.py          # Main CLI entrypoint
│   ├── config.py       # Configuration loading
│   ├── hardware.py     # Hardware detection
│   ├── memory.py       # Memory system
│   ├── chat.py         # Chat session logic
│   ├── tui.py          # Textual TUI (reserved for future)
│   ├── ollama_client.py
│   ├── hf_client.py
│   ├── models.py       # Model registry utilities
│   ├── history.py      # Session management
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
