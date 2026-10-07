<div align="center">

# AIhub

**Local AI in your terminal: chat, agents, tools and MCP, on your own models.**

[![CI](https://github.com/marceljurgiel/AIhub-TUI/actions/workflows/ci.yml/badge.svg)](https://github.com/marceljurgiel/AIhub-TUI/actions/workflows/ci.yml)
[![MIT License](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
![Linux · macOS · Windows](https://img.shields.io/badge/Linux%20·%20macOS%20·%20Windows-supported-blue)

</div>

<p align="center"><img src="docs/media/chat.gif" alt="AIhub: a question, an answer that uses what AIhub remembers about you, live tok/s and context" width="900"></p>

AIhub is a keyboard-driven terminal app for the models you run yourself with
[Ollama](https://ollama.com), on this computer or on a GPU box elsewhere on your
network. It also works with Ollama's free cloud models and with the Anthropic,
OpenAI and Google APIs.

## Install

**Linux / macOS**

```bash
curl -fsSL https://raw.githubusercontent.com/marceljurgiel/AIhub-TUI/main/install.sh | bash
```

**Windows 10 / 11** (PowerShell)

```powershell
irm https://raw.githubusercontent.com/marceljurgiel/AIhub-TUI/main/install.ps1 | iex
```

Then open a new terminal and run `aihub`.

<p align="center"><img src="docs/media/install.gif" alt="The one-line installer: uv, Python, Bun, then an Ollama server on the network" width="820"></p>

The installer needs no administrator rights and no Python or Node already
installed. It sets up:

- **uv** with its own Python 3.12, which runs the AIhub engine;
- **Bun**, which runs the terminal app;
- the **`aihub`** command;
- **Ollama**, if you want it. The installer asks whether to:
  - install Ollama on this computer;
  - use an Ollama server on your network (enter its address, e.g. `192.0.2.10`);
  - skip it for now.

  It can then download a starter model sized for your RAM.

To update, run `aihub update` or run the installer again. Your chats and
settings in `~/.aihub` are kept.

<details>
<summary>Unattended install and options</summary>

```bash
# Linux / macOS
curl -fsSL https://raw.githubusercontent.com/marceljurgiel/AIhub-TUI/main/install.sh \
  | bash -s -- --yes --ollama http://192.0.2.10:11434 --model none
#   --ollama local | skip | <server url>     --model <name> | none     --dir <path>
```

```powershell
# Windows
$env:AIHUB_YES = "1"; $env:AIHUB_OLLAMA = "local"; $env:AIHUB_MODEL = "llama3.2:3b"
irm https://raw.githubusercontent.com/marceljurgiel/AIhub-TUI/main/install.ps1 | iex
```

| Where | Linux / macOS | Windows |
|---|---|---|
| App | `~/.local/share/aihub` | `%LOCALAPPDATA%\AIhub` |
| Command | `~/.local/bin/aihub` | `%LOCALAPPDATA%\AIhub\bin\aihub.cmd` |
| Settings, chats, memory | `~/.aihub` | `%USERPROFILE%\.aihub` |

To uninstall:

- **Linux / macOS:** run `aihub uninstall`.
- **Windows:** delete `%LOCALAPPDATA%\AIhub` and remove its `bin` folder from your PATH.

Uninstalling leaves `~/.aihub` in place.
</details>

## What it does

- **Chat** with streaming answers. It shows context fill and tokens/s, and
  whether the model runs on the GPU or the CPU. Answers render as Markdown.
- **Memory** (`E`). AIhub learns facts you mention while you chat and
  uses them in later chats. Every change shows up in the chat with an undo
  link, and you can read and edit the whole memory.

<p align="center"><img src="docs/media/memory.gif" alt="AIhub learns from a remark in the chat, shows it in Memory, and knows it in a new chat" width="820"></p>
- **Tools that ask first.** The model can read and edit files, run terminal
  commands (PowerShell on Windows) and search the web. Anything that changes
  your system waits for your OK. **Agent mode** (`A`) plans and builds
  bigger tasks.

<p align="center"><img src="docs/media/agent.gif" alt="AIhub reads a project, asks before running the tests, and reports the result" width="820"></p>

- **Models** (`Ctrl+O`):
  - Browse the Ollama library and Hugging Face GGUFs, ranked by how well they
    fit your hardware or your server's.
  - Download, delete and switch models.
  - Each model shows badges for what it can do: tools, vision, thinking and cloud.
- **Ollama Cloud.** Sign in with `ollama signin` to use the big open models
  (`…:cloud`) for free, within Ollama's limits.

<p align="center"><img src="docs/media/models.gif" alt="The model picker: installed models with capabilities, models ranked for this hardware, the Ollama library and API models" width="820"></p>

- **MCP** (`C`):
  - Connect Model Context Protocol servers in one click: GitHub, Gmail,
    Google Calendar and Drive, Notion, Obsidian, Fetch, Git, Playwright,
    Context7 and Home Assistant.
  - Add any other server, or import the servers you set up for Claude.

<p align="center"><img src="docs/media/mcp.gif" alt="The MCP catalog: GitHub, Gmail, Google Calendar, Drive, Notion and more in one click" width="820"></p>

- **Images.** With a vision model, paste a screenshot with `Ctrl+V`, or drag a
  file into the terminal.
- **Skills** (`K`) are reusable instructions the model picks up when a
  request matches. You can write one in a sentence and the model drafts it,
  find one online (skills.sh, SkillsMP), or link a GitHub folder. Use it with
  `/skill <name>`.

<p align="center"><img src="docs/media/skills.gif" alt="Creating a skill from one sentence and using it on a file" width="820"></p>
- **History** (`Ctrl+R`): pick up any earlier chat.
- **Hardware** (`W`) shows your GPU, VRAM and RAM. Context size is chosen
  automatically so the model stays in GPU memory.
- **Themes** (`T`): seven colour themes (Tokyo Night, Catppuccin, Dracula,
  Nord, Gruvbox, Light…) and an accent colour of your choice, previewed live.

<p align="center"><img src="docs/media/theme.gif" alt="Switching between themes and accent colours with a live preview" width="820"></p>

- **Temperature** (`Ctrl+T`), **Settings** (`S`), **Command palette**
  (`Ctrl+P`), **Help** (`F1`).

`Ctrl+Q` quits, and `Esc` stops an answer.

### On Windows

The same app in Windows Terminal, here with a small local model on the CPU:

<p align="center"><img src="docs/media/windows.png" alt="AIhub in Windows Terminal on Windows 11" width="700"></p>

## Using an Ollama server

To run the models on a stronger machine:

1. On that machine, make Ollama listen on the network by setting
   `OLLAMA_HOST=0.0.0.0`.
2. Point AIhub at it: choose **S** in the installer, or open
   **Settings → Ollama URL** in AIhub.

AIhub learns the server's speed and GPU memory from your chats, so its model
recommendations and context sizes match that machine, not the laptop you type on.

## Command line

```bash
aihub              # start the app
aihub update       # update
aihub version
aihub cli --help   # scriptable tools: models-list, models-download, hardware-scan, chat …
```

## How it is built

```
app/   terminal UI — TypeScript, React on OpenTUI, runs on Bun
aihub/ engine — Python: Ollama/API clients, agent + tools, memory, MCP, hardware
```

The app starts the engine (`python -m aihub.bridge`) and the two talk
newline-delimited JSON over stdio.

## Development

```bash
git clone https://github.com/marceljurgiel/AIhub-TUI && cd AIhub-TUI
uv venv --python 3.12 && uv pip install -e ".[dev]"
(cd app && bun install)

.venv/bin/python -m pytest          # engine tests
(cd app && bun test && bunx tsc --noEmit)
(cd app && bun run start)           # run from the checkout
```

See [CONTRIBUTING.md](CONTRIBUTING.md). AIhub is MIT-licensed.
