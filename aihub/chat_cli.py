"""
AIHub — CLI chat session wrapper.

Thin Rich-based renderer over the event-stream engine in `aihub.chat`. Used
by `aihub chat <model>` (the subcommand). The TUI consumes the same engine
through its own worker, so this file is the only Rich-coupled chat code.
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Dict, List, Optional

import questionary
from questionary import Style
from prompt_toolkit import PromptSession
from prompt_toolkit.formatted_text import FormattedText
from prompt_toolkit.key_binding import KeyBindings
from rich import box
from rich.panel import Panel
from rich.rule import Rule
from rich.table import Table

from .chat import (
    Done, Error, RoundCompleted, TextChunk,
    ToolCallRequested, ToolCallResult,
    finalize_session, run_chat_turn, start_session,
)
from .config import config
from .console import console
from .history import list_sessions, load_session
from .memory import (
    clear_memory, extract_and_update_memory, get_memory_path,
    load_memory, update_memory_entry,
)
from .ollama_client import is_ollama_running
from .slash import (
    HELP_TEXT, KIND_CLEAR, KIND_HELP, KIND_HISTORY_BROWSE,
    KIND_MEMORY_CLEAR, KIND_MEMORY_EXTRACT, KIND_MEMORY_SAVE,
    KIND_MEMORY_SHOW, KIND_TOOLS_INFO, KIND_UNKNOWN, KIND_USAGE,
    parse_slash,
)
from .tools import get_tools_description


CHAT_STYLE = Style([
    ("qmark",       "fg:#7c3aed bold"),
    ("question",    "fg:#ffffff bold"),
    ("answer",      "fg:#7c3aed bold"),
    ("pointer",     "fg:#7c3aed bold"),
    ("highlighted", "fg:#7c3aed bold"),
    ("selected",    "fg:#a78bfa"),
    ("text",        "fg:#ffffff"),
])


# ── Visual line helpers (lifted from old chat.py for multi-line cursor) ──────

def _get_visual_line_info(text, cursor_pos, width, prompt_len):
    if cursor_pos <= width - prompt_len:
        return 0, cursor_pos + prompt_len
    rem = cursor_pos - (width - prompt_len)
    return 1 + (rem // width), rem % width


def _get_pos_from_visual(text, v_line, v_col, width, prompt_len):
    if v_line == 0:
        return max(0, v_col - prompt_len)
    return (width - prompt_len) + (v_line - 1) * width + v_col


def _make_keybindings() -> KeyBindings:
    """Prompt-toolkit bindings for the multi-line chat input."""
    bindings = KeyBindings()

    @bindings.add("backspace")
    def _(event):
        buff = event.current_buffer
        if buff.selection_state is not None:
            buff.cut_selection()
        else:
            buff.delete_before_cursor(count=1)

    @bindings.add("delete")
    def _(event):
        buff = event.current_buffer
        if buff.selection_state is not None:
            buff.cut_selection()
        else:
            buff.delete(count=1)

    @bindings.add("enter")
    def _(event):
        event.current_buffer.validate_and_handle()

    @bindings.add("c-a")
    def _(event):
        buff = event.current_buffer
        buff.cursor_position = 0
        buff.start_selection()
        buff.cursor_position = len(buff.text)

    @bindings.add("escape", "enter")
    def _(event):
        event.current_buffer.insert_text("\n")

    @bindings.add("up")
    def _(event):
        buff = event.current_buffer
        if "\n" in buff.text:
            buff.auto_up()
            return
        width = event.app.output.get_size().columns
        v_line, v_col = _get_visual_line_info(buff.text, buff.cursor_position, width, 5)
        if v_line > 0:
            buff.cursor_position = min(
                len(buff.text),
                _get_pos_from_visual(buff.text, v_line - 1, v_col, width, 5),
            )
        else:
            buff.auto_up()

    @bindings.add("down")
    def _(event):
        buff = event.current_buffer
        if "\n" in buff.text:
            buff.auto_down()
            return
        width = event.app.output.get_size().columns
        v_line, v_col = _get_visual_line_info(buff.text, buff.cursor_position, width, 5)
        max_v_line, _ = _get_visual_line_info(buff.text, len(buff.text), width, 5)
        if v_line < max_v_line:
            buff.cursor_position = min(
                len(buff.text),
                _get_pos_from_visual(buff.text, v_line + 1, v_col, width, 5),
            )
        else:
            buff.auto_down()

    return bindings


# ── Top-level entry point ────────────────────────────────────────────────────

def run_chat_session(
    model_name: str,
    is_api: bool = False,
    initial_messages: Optional[List[Dict[str, Any]]] = None,
    context_length: Optional[int] = None,
) -> None:
    """Run an interactive Rich/prompt_toolkit chat session.

    Consumes the event-stream engine in `aihub.chat`. Slash commands are
    dispatched through `_handle_slash` below.
    """
    if not is_api and not is_ollama_running():
        console.print(Panel(
            "[red]Ollama is not running.[/red]\n"
            "Start it with: [bold white]ollama serve[/bold white]  (Linux/macOS)\n"
            "or launch the [bold white]Ollama[/bold white] application (Windows).",
            title="[bold red]Connection Error[/bold red]",
            border_style="red",
        ))
        return

    temperature = _prompt_temperature()
    if context_length is None:
        context_length = _prompt_context_length(model_name)

    # ── Build messages: optionally resume, then inject memory ───────────────
    messages: List[Dict[str, Any]] = []
    start_time = datetime.now()

    if initial_messages:
        messages = list(initial_messages)
        _render_loaded_history(messages)
    else:
        sessions = list_sessions(model_name)
        if sessions:
            try:
                resume = questionary.confirm(
                    f"Resume last session? ({sessions[0]['message_count']} messages, "
                    f"{sessions[0]['start_time'][:19]})",
                    default=False, style=CHAT_STYLE,
                ).ask()
            except (KeyboardInterrupt, EOFError):
                resume = False
            if resume:
                messages = load_session(model_name, sessions[0]["filename"])
                console.print(f"[dim]Loaded {len(messages)} messages from previous session.[/dim]")

    messages = start_session(model_name, messages)

    has_memory = any(m.get("role") == "system" for m in messages)
    if has_memory:
        console.print(f"[dim]📝 Memory loaded from {get_memory_path(model_name)}[/dim]")

    tools_available = config.tools_enabled and not is_api
    _render_session_header(model_name, temperature, context_length, has_memory, tools_available)

    pt_session = PromptSession(key_bindings=_make_keybindings())

    while True:
        try:
            user_input = pt_session.prompt(
                FormattedText([("fg:#7c3aed bold", "You: ")]),
                mouse_support=True, multiline=True,
            )
        except (KeyboardInterrupt, EOFError):
            console.print("\n[bold #a78bfa]Chat interrupted.[/bold #a78bfa]")
            break

        stripped = user_input.strip()
        if stripped.lower() in ("exit", "quit", "bye", "q"):
            console.print("[bold #a78bfa]Chat ended.[/bold #a78bfa]")
            break
        if not stripped:
            continue

        if stripped.startswith("/"):
            _handle_slash(stripped, model_name, messages)
            continue

        messages.append({"role": "user", "content": user_input})

        if is_api:
            # API integration stub — preserved to match old behaviour.
            stub = (
                f"[Cloud API stub — {model_name}] "
                "Configure your API key in ~/.aihub/config.yaml to use real cloud responses."
            )
            console.print(f"[bold white]AIHub[/bold white]: {stub}")
            messages.append({"role": "assistant", "content": stub})
            console.print()
            continue

        fatal = _stream_turn(
            model_name, messages,
            temperature=temperature, context_length=context_length,
            tools_enabled=tools_available,
        )
        if fatal:
            break

    saved = finalize_session(model_name, messages, temperature, start_time)
    if saved:
        console.print(f"[dim]💾 Session saved.[/dim]")


# ── Stream renderer ──────────────────────────────────────────────────────────

def _stream_turn(
    model_name: str,
    messages: List[Dict[str, Any]],
    *,
    temperature: float,
    context_length: Optional[int],
    tools_enabled: bool,
) -> bool:
    """Render one turn's events to the terminal. Returns True on fatal error."""
    last_round_had_text = False
    current_round = -1
    for event in run_chat_turn(
        model_name, messages,
        temperature=temperature,
        context_length=context_length,
        tools_enabled=tools_enabled,
    ):
        if isinstance(event, TextChunk):
            if event.round_index != current_round:
                if current_round >= 0:
                    console.print()  # close previous round
                console.print("[bold white]AIHub[/bold white]: ", end="")
                current_round = event.round_index
                last_round_had_text = False
            console.print(event.text, end="")
            last_round_had_text = True
        elif isinstance(event, ToolCallRequested):
            if last_round_had_text:
                console.print()
            console.print(Panel(
                f"[bold cyan]Tool:[/bold cyan] [white]{event.name}[/white]\n"
                f"[dim]Args: {json.dumps(event.arguments, ensure_ascii=False)}[/dim]",
                title="[bold #7c3aed]🔧 Calling Tool[/bold #7c3aed]",
                border_style="cyan", padding=(0, 1),
            ))
        elif isinstance(event, ToolCallResult):
            preview = event.result[:2000] + ("…" if len(event.result) > 2000 else "")
            border = "red" if event.error else "dim cyan"
            console.print(Panel(
                preview,
                title=f"[bold cyan]🔧 Tool Output: {event.name}  [{event.duration_ms}ms][/bold cyan]",
                border_style=border, padding=(0, 1),
            ))
        elif isinstance(event, RoundCompleted):
            if last_round_had_text:
                console.print()
            last_round_had_text = False
        elif isinstance(event, Done):
            return False
        elif isinstance(event, Error):
            colour = "red" if event.fatal else "yellow"
            console.print(f"\n[bold {colour}]{event.message}[/bold {colour}]")
            if event.fatal:
                return True
    return False


# ── Slash-command dispatcher (CLI side) ──────────────────────────────────────

def _handle_slash(raw: str, model_name: str, messages: List[Dict[str, Any]]) -> None:
    result = parse_slash(raw)
    kind = result.kind

    if kind == KIND_HELP:
        console.print(Panel(
            HELP_TEXT,
            title="[bold #7c3aed]Help[/bold #7c3aed]",
            border_style="#7c3aed",
        ))
    elif kind == KIND_TOOLS_INFO:
        console.print(Panel(
            get_tools_description(),
            title="[bold cyan]🔧 Available Tools[/bold cyan]",
            border_style="cyan",
        ))
    elif kind == KIND_CLEAR:
        system = [m for m in messages if m.get("role") == "system"]
        messages.clear()
        messages.extend(system)
        console.print("[dim]Chat context cleared.[/dim]")
    elif kind == KIND_MEMORY_SHOW:
        mem = load_memory(model_name)
        if mem:
            console.print(Panel(
                mem,
                title=f"[bold #7c3aed]📝 Memory: {model_name}[/bold #7c3aed]",
                border_style="#7c3aed",
            ))
        else:
            console.print(f"[dim]No memory stored for {model_name}.[/dim]")
            console.print("[dim]Use /memory save <key> <value> to add entries.[/dim]")
    elif kind == KIND_MEMORY_SAVE:
        key = result.payload["key"]
        value = result.payload["value"]
        update_memory_entry(model_name, key, value)
        console.print(f"[green]✔ Memory saved:[/green] [cyan]{key}[/cyan] → {value}")
    elif kind == KIND_MEMORY_CLEAR:
        try:
            confirmed = questionary.confirm(
                f"Delete all memory for {model_name}?",
                default=False, style=CHAT_STYLE,
            ).ask()
        except (KeyboardInterrupt, EOFError):
            confirmed = False
        if confirmed:
            cleared = clear_memory(model_name)
            console.print(
                "[green]✔ Memory cleared.[/green]" if cleared
                else "[dim]No memory file found.[/dim]"
            )
    elif kind == KIND_MEMORY_EXTRACT:
        target = result.payload["target"]
        with console.status(
            f"[bold cyan]Extracting key information for {target} memory...[/bold cyan]"
        ):
            outcome = extract_and_update_memory(model_name, messages, target=target)
        if outcome.startswith("Error:"):
            console.print(f"[bold red]⚠ {outcome}[/bold red]")
        else:
            console.print(Panel(
                outcome,
                title=f"[bold green]✔ Facts added to {target.capitalize()} Memory[/bold green]",
                border_style="green",
            ))
    elif kind == KIND_HISTORY_BROWSE:
        _render_history_browser(model_name, messages)
    elif kind == KIND_USAGE:
        console.print(f"[yellow]{result.message}[/yellow]")
    elif kind == KIND_UNKNOWN:
        console.print(f"[yellow]{result.message}[/yellow]")


# ── Prompts and renderers ────────────────────────────────────────────────────

def _prompt_temperature() -> float:
    try:
        raw = questionary.text(
            "Temperature (0.0–2.0):",
            default="0.7", style=CHAT_STYLE,
        ).ask()
        if raw is None:
            return 0.7
        return max(0.0, min(2.0, float(raw)))
    except (ValueError, TypeError, KeyboardInterrupt, EOFError):
        console.print("[dim]Using default temperature 0.7[/dim]")
        return 0.7


def _prompt_context_length(model_name: str) -> int:
    try:
        from .hardware import estimate_kv_cache_gb
        default_ctx = config.default_context_length
        default_gb = estimate_kv_cache_gb(default_ctx, model_name)
        raw = questionary.text(
            f"Context Length (tokens) [Default {default_ctx} | ~{default_gb}GB VRAM]:",
            default=str(default_ctx), style=CHAT_STYLE,
        ).ask()
        if raw:
            return int(raw)
        return default_ctx
    except (ValueError, TypeError, KeyboardInterrupt, EOFError):
        return config.default_context_length
    except Exception:
        return config.default_context_length


def _render_loaded_history(messages: List[Dict[str, Any]]) -> None:
    console.print(Rule("[dim]Loaded History[/dim]", style="#555555"))
    for msg in messages:
        role = msg.get("role", "")
        content = msg.get("content", "")
        if role == "system" or not content:
            continue
        color = "#a78bfa" if role == "assistant" else "#7c3aed"
        name = "AIHub" if role == "assistant" else "You"
        console.print(f"[bold {color}]{name}:[/bold {color}] {content}")
        console.print()
    console.print(Rule(style="#555555"))


def _render_session_header(
    model_name: str, temperature: float, context_length: int,
    has_memory: bool, tools_available: bool,
) -> None:
    from .hardware import estimate_kv_cache_gb
    kv = estimate_kv_cache_gb(context_length, model_name)
    memory_indicator = "📝 memory" if has_memory else "no memory"
    tool_indicator = "🔧 tools enabled" if tools_available else "no tools"
    console.print()
    console.print(Panel(
        f"[bold white]{model_name}[/bold white]  "
        f"[dim]temp={temperature:.1f}  |  ctx={context_length // 1024}k "
        f"(+{kv}GB VRAM)  |  {memory_indicator}  |  {tool_indicator}[/dim]\n"
        f"[dim]Type 'exit' or 'quit' to leave  |  type /help for commands[/dim]",
        title="[bold #7c3aed]Chat Session[/bold #7c3aed]",
        border_style="#7c3aed",
    ))
    console.print()


def _render_history_browser(model_name: str, messages: List[Dict[str, Any]]) -> None:
    sessions = list_sessions(model_name)
    if not sessions:
        console.print(f"[dim]No history for {model_name} yet.[/dim]")
        return

    table = Table(
        title=f"[bold #7c3aed]📚 History: {model_name}[/bold #7c3aed]",
        box=box.ROUNDED, border_style="#555555",
        header_style="bold #a78bfa", show_lines=True,
    )
    table.add_column("#", width=3, justify="right")
    table.add_column("Date", min_width=19)
    table.add_column("Messages", justify="right")
    table.add_column("Temp", justify="right", style="cyan")
    for i, s in enumerate(sessions[:20], 1):
        table.add_row(
            str(i),
            s["start_time"][:19].replace("T", " "),
            str(s["message_count"]),
            f"{s['temperature']:.1f}",
        )
    console.print(table)

    choices = [
        questionary.Choice(
            f"{i}. {s['start_time'][:19].replace('T', ' ')} ({s['message_count']} msgs)",
            value=s["filename"],
        )
        for i, s in enumerate(sessions[:20], 1)
    ]
    choices.append(questionary.Choice("← Cancel", value=None))

    try:
        selected = questionary.select(
            "Load a session into current context?",
            choices=choices, style=CHAT_STYLE,
        ).ask()
    except (KeyboardInterrupt, EOFError):
        selected = None

    if not selected:
        return
    loaded = load_session(model_name, selected)
    if not loaded:
        console.print("[yellow]Could not load that session.[/yellow]")
        return
    system = [m for m in messages if m.get("role") == "system"]
    messages.clear()
    messages.extend(system)
    messages.extend([m for m in loaded if m.get("role") != "system"])
    console.print(f"[green]✔ Loaded {len(messages)} messages.[/green]")
