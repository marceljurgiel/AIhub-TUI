"""
AIHub - Chat session module (v0.1.0).
Handles interactive streaming chat sessions with:
  - Memory injection (per-model .md files)
  - Session history (auto-save on exit)
  - Tool calling (terminal, file ops, web search, file search)
  - Slash-commands: /memory, /history, /tools, /clear, /help
"""
import json
import sys
from datetime import datetime
from rich.console import Console
from rich.prompt  import Prompt
from rich.panel   import Panel
from rich.rule    import Rule
from rich.table   import Table
from rich         import box
import questionary
from questionary import Style
from prompt_toolkit import PromptSession
from prompt_toolkit.formatted_text import FormattedText
from prompt_toolkit.key_binding import KeyBindings

from .console import console
from .ollama_client import chat_stream, is_ollama_running
from .memory        import load_memory, save_memory, update_memory_entry, clear_memory, build_system_prompt, get_memory_path
from .history       import save_session, list_sessions, load_session
from .config        import config
from .tools         import run_tool, get_tools_description, TOOLS_SCHEMA
from typing import List, Dict, Any, Optional

CHAT_STYLE = Style([
    ("qmark",       "fg:#7c3aed bold"),
    ("question",    "fg:#ffffff bold"),
    ("answer",      "fg:#7c3aed bold"),
    ("pointer",     "fg:#7c3aed bold"),
    ("highlighted", "fg:#7c3aed bold"),
    ("selected",    "fg:#a78bfa"),
    ("text",        "fg:#ffffff"),
])


# ─── Slash-command help text ────────────────────────────────────────────────

_HELP_TEXT = """
[bold #a78bfa]Available slash-commands:[/bold #a78bfa]

  [cyan]/help[/cyan]                       Show this help
  [cyan]/memory[/cyan]                     Show current memory for this model
  [cyan]/memory save <key> <value>[/cyan]  Save a key→value entry to memory
  [cyan]/memory clear[/cyan]               Delete all memory for this model
  [cyan]/history[/cyan]                    Browse & resume past sessions
  [cyan]/tools[/cyan]                      List available agentic tools
  [cyan]/memoryadd global[/cyan]           Extract facts from this chat into Global Memory
  [cyan]/memoryadd chat[/cyan]             Extract facts from this chat into Model Memory
  [cyan]/clear[/cyan]                      Clear the current chat context (start fresh)
  [cyan]exit / quit / q[/cyan]            End the chat session
"""


# ─── Visual line helpers ───────────────────────────────────────────────────────

def get_visual_line_info(text, cursor_pos, width, prompt_len):
    if cursor_pos <= width - prompt_len:
        return 0, cursor_pos + prompt_len
    rem = cursor_pos - (width - prompt_len)
    v_line = 1 + (rem // width)
    v_col = rem % width
    return v_line, v_col

def get_pos_from_visual(text, v_line, v_col, width, prompt_len):
    if v_line == 0:
        return max(0, v_col - prompt_len)
    else:
        return (width - prompt_len) + (v_line - 1) * width + v_col


# ─── Main chat entry point ───────────────────────────────────────────────────

def run_chat_session(model_name: str, is_api: bool = False, initial_messages: Optional[List[Dict[str, Any]]] = None, context_length: Optional[int] = None):
    """
    Run an interactive streaming chat session.

    Args:
        model_name:       Name of the Ollama model or API model.
        is_api:           If True, uses the cloud API stub instead of Ollama.
        initial_messages: Optional list of messages to start with.
        context_length:   Optional context window size override.
    """
    if not is_api and not is_ollama_running():
        console.print(Panel(
            "[red]Ollama is not running.[/red]\n"
            "Start it with: [bold white]ollama serve[/bold white]  (Linux/macOS)\n"
            "or launch the [bold white]Ollama[/bold white] application (Windows).",
            title="[bold red]Connection Error[/bold red]",
            border_style="red"
        ))
        return

    # ── Temperature selection ────────────────────────────────────────────────
    temperature = 0.7
    try:
        temp_str = questionary.text(
            "Temperature (0.0–2.0):",
            default="0.7",
            style=CHAT_STYLE
        ).ask()
        if temp_str is not None:
            temperature = max(0.0, min(2.0, float(temp_str)))
    except (ValueError, TypeError):
        console.print("[dim]Using default temperature 0.7[/dim]")

    # ── Context Length selection ─────────────────────────────────────────────
    if context_length is None:
        try:
            from .hardware import estimate_kv_cache_gb
            default_ctx = config.default_context_length
            default_gb  = estimate_kv_cache_gb(default_ctx, model_name)
            
            ctx_str = questionary.text(
                f"Context Length (tokens) [Default {default_ctx} | ~{default_gb}GB VRAM]:",
                default=str(default_ctx),
                style=CHAT_STYLE
            ).ask()
            if ctx_str:
                context_length = int(ctx_str)
        except (ValueError, TypeError):
            context_length = config.default_context_length
        except Exception:
            context_length = config.default_context_length

    # ── Load or resume history ───────────────────────────────────────────────
    messages = []
    start_time = datetime.now()

    if initial_messages:
        messages = initial_messages
        # Render the loaded history
        console.print(Rule("[dim]Loaded History[/dim]", style="#555555"))
        for msg in messages:
            role    = msg.get("role", "")
            content = msg.get("content", "")
            if role == "system" or not content:
                continue
            color = "#a78bfa" if role == "assistant" else "#7c3aed"
            name  = "AIHub" if role == "assistant" else "You"
            console.print(f"[bold {color}]{name}:[/bold {color}] {content}")
            console.print()
        console.print(Rule(style="#555555"))
    else:
        sessions = list_sessions(model_name)
        if sessions:
            resume = questionary.confirm(
                f"Resume last session? ({sessions[0]['message_count']} messages, "
                f"{sessions[0]['start_time'][:19]})",
                default=False,
                style=CHAT_STYLE
            ).ask()
            if resume:
                messages = load_session(model_name, sessions[0]["filename"])
                console.print(f"[dim]Loaded {len(messages)} messages from previous session.[/dim]")

    # ── Load memory and inject as system prompt ──────────────────────────────
    system_prompt = build_system_prompt(model_name)
    if system_prompt:
        # Insert/replace the system message at position 0
        if messages and messages[0].get("role") == "system":
            messages[0]["content"] = system_prompt
        else:
            messages.insert(0, {"role": "system", "content": system_prompt})
        console.print(f"[dim]📝 Memory loaded from {get_memory_path(model_name)}[/dim]")

    # ── Whether this model supports tool calls ───────────────────────────────
    tools_available = config.tools_enabled and not is_api

    # ── Print session header ─────────────────────────────────────────────────
    console.print()
    memory_indicator = "📝 memory" if system_prompt else "no memory"
    tool_indicator   = "🔧 tools enabled" if tools_available else "no tools"
    # Calculate Effective Context Length and Memory Impact
    eff_ctx = context_length or config.default_context_length
    from .hardware import estimate_kv_cache_gb
    kv_cache_gb = estimate_kv_cache_gb(eff_ctx, model_name)
    
    console.print(Panel(
        f"[bold white]{model_name}[/bold white]  "
        f"[dim]temp={temperature:.1f}  |  ctx={eff_ctx//1024}k (+{kv_cache_gb}GB VRAM)  |  {memory_indicator}  |  {tool_indicator}[/dim]\n"
        f"[dim]Type 'exit' or 'quit' to leave  |  type /help for commands[/dim]",
        title="[bold #7c3aed]Chat Session[/bold #7c3aed]",
        border_style="#7c3aed"
    ))
    console.print()

    # ─── Main chat loop ──────────────────────────────────────────────────────
    bindings = KeyBindings()

    @bindings.add('backspace')
    def _(event):
        buff = event.current_buffer
        if buff.selection_state is not None:
            buff.cut_selection()
        else:
            buff.delete_before_cursor(count=1)

    @bindings.add('delete')
    def _(event):
        buff = event.current_buffer
        if buff.selection_state is not None:
            buff.cut_selection()
        else:
            buff.delete(count=1)

    @bindings.add('enter')
    def _(event):
        event.current_buffer.validate_and_handle()

    @bindings.add('c-a')
    def _(event):
        buff = event.current_buffer
        buff.cursor_position = 0
        buff.start_selection()
        buff.cursor_position = len(buff.text)

    @bindings.add('escape', 'enter')
    def _(event):
        event.current_buffer.insert_text('\n')

    @bindings.add('up')
    def _(event):
        buff = event.current_buffer
        if '\n' in buff.text:
            buff.auto_up()
            return
        width = event.app.output.get_size().columns
        v_line, v_col = get_visual_line_info(buff.text, buff.cursor_position, width, 5)
        if v_line > 0:
            new_pos = get_pos_from_visual(buff.text, v_line - 1, v_col, width, 5)
            buff.cursor_position = min(len(buff.text), new_pos)
        else:
            buff.auto_up()

    @bindings.add('down')
    def _(event):
        buff = event.current_buffer
        if '\n' in buff.text:
            buff.auto_down()
            return
        width = event.app.output.get_size().columns
        v_line, v_col = get_visual_line_info(buff.text, buff.cursor_position, width, 5)
        max_v_line, _ = get_visual_line_info(buff.text, len(buff.text), width, 5)
        if v_line < max_v_line:
            new_pos = get_pos_from_visual(buff.text, v_line + 1, v_col, width, 5)
            buff.cursor_position = min(len(buff.text), new_pos)
        else:
            buff.auto_down()

    pt_session = PromptSession(key_bindings=bindings)
    
    while True:
        try:
            user_input = pt_session.prompt(
                FormattedText([("fg:#7c3aed bold", "You: ")]),
                mouse_support=True,
                multiline=True
            )
        except (KeyboardInterrupt, EOFError):
            console.print("\n[bold #a78bfa]Chat interrupted.[/bold #a78bfa]")
            break

        user_stripped = user_input.strip()

        # ── Exit commands ────────────────────────────────────────────────────
        if user_stripped.lower() in ("exit", "quit", "bye", "q"):
            console.print("[bold #a78bfa]Chat ended. Returning to menu…[/bold #a78bfa]")
            break

        if not user_stripped:
            continue

        # ── Slash-commands ───────────────────────────────────────────────────
        if user_stripped.startswith("/"):
            _handle_slash_command(user_stripped, model_name, messages)
            continue

        # ── Append user message ──────────────────────────────────────────────
        messages.append({"role": "user", "content": user_input})

        # ── Cloud API stub ───────────────────────────────────────────────────
        if is_api:
            import time
            time.sleep(0.3)
            full_response = (
                f"[Cloud API stub — {model_name}] "
                "Configure your API key in ~/.aihub/config.yaml to use real cloud responses."
            )
            console.print(f"[bold white]AIHub[/bold white]: {full_response}")
            messages.append({"role": "assistant", "content": full_response})
            console.print()
            continue

        # ── Streaming Ollama response (with optional tool calling) ───────────
        full_response = _stream_with_tools(
            model_name, messages, temperature, tools_available, context_length=context_length
        )
        if full_response is None:
            # Fatal error — end session gracefully
            break

        messages.append({"role": "assistant", "content": full_response})
        console.print()

    # ── Auto-save session history ────────────────────────────────────────────
    user_messages = [m for m in messages if m.get("role") == "user"]
    if user_messages:
        saved = save_session(model_name, messages, temperature, start_time)
        if saved:
            console.print(f"[dim]💾 Session saved.[/dim]")


# ─── Tool-calling streaming loop ─────────────────────────────────────────────

def _stream_with_tools(
    model_name: str,
    messages: List[Dict[str, Any]],
    temperature: float,
    tools_available: bool,
    max_tool_rounds: int = 25,
    context_length: Optional[int] = None
) -> Optional[str]:
    """
    Stream a response from Ollama, handling tool calls in a loop.

    If the model requests tool calls, executes them and feeds results back
    until the model produces a final text response or max_tool_rounds is hit.

    Returns the final assistant text, or None on a fatal error.
    """
    for _round in range(max_tool_rounds):
        full_response = ""
        tool_calls_detected = []
        raw_chunks = []

        console.print("[bold white]AIHub[/bold white]: ", end="")

        try:
            stream_kwargs = {}
            if tools_available:
                stream_kwargs["tools"] = TOOLS_SCHEMA

            tool_call_error = None
            for chunk in chat_stream(model_name, messages, temperature, context_length=context_length, **stream_kwargs):
                if "error" in chunk:
                    err_msg = str(chunk["error"])
                    # Check if model doesn't support tools
                    if "does not support tools" in err_msg and stream_kwargs.get("tools"):
                        tool_call_error = err_msg
                        break
                    console.print(f"\n[bold red]API Error: {chunk['error']}[/bold red]")
                    return None

                raw_chunks.append(chunk)
                msg = chunk.get("message", {})

                # Accumulate text content
                piece = msg.get("content", "")
                if piece:
                    full_response += piece
                    console.print(piece, end="")

                # Collect tool call requests (may arrive across multiple chunks)
                for tc in msg.get("tool_calls", []):
                    tool_calls_detected.append(tc)
            
            # If model doesn't support tools, retry without
            if tool_call_error and stream_kwargs.get("tools"):
                console.print(f"\n[dim]Model doesn't support tools, retrying without...[/dim]")
                stream_kwargs.pop("tools", None)
                full_response = ""
                tool_calls_detected = []
                for chunk in chat_stream(model_name, messages, temperature, context_length=context_length, **stream_kwargs):
                    if "error" in chunk:
                        console.print(f"\n[bold red]API Error: {chunk['error']}[/bold red]")
                        return None
                    msg = chunk.get("message", {})
                    piece = msg.get("content", "")
                    if piece:
                        full_response += piece
                        console.print(piece, end="")
                    for tc in msg.get("tool_calls", []):
                        tool_calls_detected.append(tc)

        except Exception as exc:
            console.print(f"\n[bold red]Unexpected error: {exc}[/bold red]")
            return None

        console.print()  # newline after streaming

        # ── No tool calls → return final text ───────────────────────────────
        if not tool_calls_detected:
            return full_response

        # ── Handle tool calls ────────────────────────────────────────────────
        # Append assistant message with tool_calls metadata
        messages.append({
            "role":       "assistant",
            "content":    full_response,
            "tool_calls": tool_calls_detected,
        })

        for tc in tool_calls_detected:
            fn   = tc.get("function", {})
            name = fn.get("name", "")
            args = fn.get("arguments", {})
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except Exception:
                    args = {}

            # Show tool-use indicator
            console.print()
            console.print(Panel(
                f"[bold cyan]Tool:[/bold cyan] [white]{name}[/white]\n"
                f"[dim]Args: {json.dumps(args, ensure_ascii=False)}[/dim]",
                title="[bold #7c3aed]🔧 Calling Tool[/bold #7c3aed]",
                border_style="cyan",
                padding=(0, 1)
            ))

            # Execute the tool
            result = run_tool(name, **args)

            # Show tool output
            console.print(Panel(
                result[:2000] + ("…" if len(result) > 2000 else ""),
                title=f"[bold cyan]🔧 Tool Output: {name}[/bold cyan]",
                border_style="dim cyan",
                padding=(0, 1)
            ))

            # Feed tool result back to the model
            messages.append({
                "role":    "tool",
                "content": result,
            })

        # Loop — let the model respond again with the tool output in context

    # Exceeded max_tool_rounds - check if we got stuck in a loop
    if full_response:
        console.print(Panel(
            f"[yellow]⚠ Tool-call loop limit reached ({max_tool_rounds} rounds).[/yellow]\n"
            "[dim]The model is still requesting tools or stuck in a loop.[/dim]",
            title="[bold yellow]Loop Limit[/bold yellow]",
            border_style="yellow"
        ))
    return full_response


# ─── Slash-command handler ───────────────────────────────────────────────────

def _handle_slash_command(cmd: str, model_name: str, messages: list):
    """Process a slash-command entered during a chat session."""
    parts = cmd.split(maxsplit=2)
    command = parts[0].lower()

    # ── /help ────────────────────────────────────────────────────────────────
    if command == "/help":
        console.print(Panel(_HELP_TEXT, title="[bold #7c3aed]Help[/bold #7c3aed]",
                            border_style="#7c3aed"))

    # ── /tools ───────────────────────────────────────────────────────────────
    elif command == "/tools":
        console.print(Panel(
            get_tools_description(),
            title="[bold cyan]🔧 Available Tools[/bold cyan]",
            border_style="cyan"
        ))

    # ── /clear ───────────────────────────────────────────────────────────────
    elif command == "/clear":
        # Keep system message if present, clear everything else
        system = [m for m in messages if m.get("role") == "system"]
        messages.clear()
        messages.extend(system)
        console.print("[dim]Chat context cleared.[/dim]")

    # ── /memory ──────────────────────────────────────────────────────────────
    elif command == "/memory":
        sub = parts[1].lower() if len(parts) > 1 else ""

        if sub == "save" and len(parts) == 3:
            # /memory save <key> <value>
            kv = parts[2].split(maxsplit=1)
            if len(kv) != 2:
                console.print("[yellow]Usage: /memory save <key> <value>[/yellow]")
                return
            key, value = kv
            update_memory_entry(model_name, key, value)
            console.print(f"[green]✔ Memory saved:[/green] [cyan]{key}[/cyan] → {value}")

        elif sub == "clear":
            if questionary.confirm(
                f"Delete all memory for {model_name}?",
                default=False, style=CHAT_STYLE
            ).ask():
                cleared = clear_memory(model_name)
                console.print("[green]✔ Memory cleared.[/green]" if cleared
                              else "[dim]No memory file found.[/dim]")

            else:
                # /memory — show current memory
                mem = load_memory(model_name)
                if mem:
                    console.print(Panel(
                        mem,
                        title=f"[bold #7c3aed]📝 Memory: {model_name}[/bold #7c3aed]",
                        border_style="#7c3aed"
                    ))
                else:
                    console.print(f"[dim]No memory stored for {model_name}.[/dim]")
                    console.print("[dim]Use /memory save <key> <value> to add entries.[/dim]")

    # ── /memoryadd ───────────────────────────────────────────────────────────
    elif command == "/memoryadd":
        target = parts[1].lower() if len(parts) > 1 else "chat"
        if target not in ("global", "chat"):
            console.print("[yellow]Usage: /memoryadd [global|chat][/yellow]")
            return

        from .memory import extract_and_update_memory
        
        with console.status(f"[bold cyan]Extracting key information for {target} memory...[/bold cyan]"):
            result = extract_and_update_memory(model_name, messages, target=target)
            
        if result.startswith("Error:"):
            console.print(f"[bold red]⚠ {result}[/bold red]")
        else:
            console.print(Panel(
                result,
                title=f"[bold green]✔ Facts added to {target.capitalize()} Memory[/bold green]",
                border_style="green"
            ))

    # ── /history ─────────────────────────────────────────────────────────────
    elif command == "/history":
        sessions = list_sessions(model_name)
        if not sessions:
            console.print(f"[dim]No history for {model_name} yet.[/dim]")
            return

        table = Table(
            title=f"[bold #7c3aed]📚 History: {model_name}[/bold #7c3aed]",
            box=box.ROUNDED, border_style="#555555",
            header_style="bold #a78bfa", show_lines=True
        )
        table.add_column("#",       width=3,  justify="right")
        table.add_column("Date",    min_width=19)
        table.add_column("Messages", justify="right")
        table.add_column("Temp",    justify="right", style="cyan")

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
                value=s["filename"]
            )
            for i, s in enumerate(sessions[:20], 1)
        ]
        choices.append(questionary.Choice("← Cancel", value=None))

        selected = questionary.select(
            "Load a session into current context?",
            choices=choices,
            style=CHAT_STYLE
        ).ask()

        if selected:
            loaded = load_session(model_name, selected)
            if loaded:
                # Replace messages (keep system if present)
                system = [m for m in messages if m.get("role") == "system"]
                messages.clear()
                messages.extend(system)
                messages.extend([m for m in loaded if m.get("role") != "system"])
                console.print(f"[green]✔ Loaded {len(messages)} messages.[/green]")

    else:
        console.print(f"[yellow]⚠ Unknown command: {command}. Type /help for help.[/yellow]")
