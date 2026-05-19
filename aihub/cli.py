"""
AIHub CLI - Main entrypoint (v0.1.4).
Provides a persistent interactive TUI shell for managing local and API-based AI models.

v0.1.4 changes:
  - Browse & Manage Models redesigned: chat/agentic models only (image/video removed)
  - Hardware-based filtering: models sorted by best-fit for available RAM/VRAM
  - Installed models shown first with green highlight
  - Capability badges (🔧 Tool Calling, 💻 Code, 🧠 Reasoning, etc.) on model cards
  - Expanded model registry: 55+ models across all major families
  - Category filter: Small / Medium / Large / XLarge
  - Inline search by name or capability
"""
import sys
import os
import json
import typer
import questionary
from questionary import Style
from rich.table   import Table
from rich.panel   import Panel
from rich.text    import Text
from rich.columns import Columns
from rich.rule    import Rule
from rich         import box
import requests
import yaml
from prompt_toolkit.shortcuts import confirm

from .console       import console
from .config        import config, CONFIG_FILE, load_config, save_config
from .hardware      import get_gpu_info, get_cpu_info, get_ram_info, get_disk_info, get_os_info, score_hardware, estimate_tokens_per_sec, get_available_ram_gb
from .ollama_client import get_local_models, get_local_model_sizes, pull_model_stream, is_ollama_running, get_model_info, unload_model
from .hf_client     import fetch_hf_models, get_hf_error
from .chat          import run_chat_session
from .history       import list_sessions, load_session, delete_session, get_history_dir
from .models        import categorize_model, get_capability_badges, get_speed_label, get_speed_color, sort_models_for_hardware, CATEGORIES

app = typer.Typer(
    help="AIHub 0.1.4 — Your all-in-one local AI management platform.",
    invoke_without_command=True
)
LAST_MODEL_USED = None  # Global to track the last model used for unloading on exit

# ─── OpenCode-inspired questionary style ─────────────────────────────────────
CUSTOM_STYLE = Style([
    ("qmark",        "fg:#7c3aed bold"),
    ("question",     "fg:#ffffff bold"),
    ("answer",       "fg:#7c3aed bold"),
    ("pointer",      "fg:#7c3aed bold"),
    ("highlighted",  "fg:#7c3aed bold"),
    ("selected",     "fg:#a78bfa"),
    ("separator",    "fg:#555555"),
    ("instruction",  "fg:#888888"),
    ("text",         "fg:#ffffff"),
    ("disabled",     "fg:#444444 italic"),
])

# ─── Source badge colors ──────────────────────────────────────────────────────
_SOURCE_BADGE = {
    "registry":    "[dim white][Reg][/dim white]",
    "ollama":      "[green][Ollama][/green]",
    "huggingface": "[bold yellow][HF][/bold yellow]",
}


def load_registry_models() -> list:
    """
    Build the full model list by merging two sources (v0.1.4 — chat/agentic only):
      1. Static JSON registry (models_registry.json) — chat/text models only
      2. Live Ollama models from /api/tags

    Image and video models are excluded entirely.
    Each entry gets a 'source' field: 'registry' or 'ollama'.
    Duplicate model names are deduplicated (first occurrence wins).
    """
    registry = []

    # ── 1. Static registry ───────────────────────────────────────────────────
    try:
        with open(config.models_registry_path, "r", encoding="utf-8") as f:
            raw = json.load(f)
        for m in raw:
            # Skip image/video models entirely
            if m.get("type") in ("image", "video"):
                continue
            m.setdefault("source", "registry")
            m.setdefault("type", "chat")
            registry.append(m)
    except Exception as e:
        console.print(f"[bold red]⚠  Could not read model registry: {e}[/bold red]")

    for m in registry:
        m["category"] = categorize_model(m["name"], m.get("tags", []))

    known_names = {m["name"] for m in registry}

    # ── 2. Live Ollama models (locally installed, not in registry) ────────────
    try:
        response = requests.get(f"{config.ollama_api_url}/api/tags", timeout=2)
        if response.status_code == 200:
            local_models = response.json().get("models", [])
            for lm in local_models:
                name = lm["name"]
                if name not in known_names:
                    size_gb = round(lm.get("size", 0) / (1024 ** 3), 2)
                    tags = ["Local", "Ollama"]
                    registry.append({
                        "name":             name,
                        "type":             "chat",
                        "url":              name,
                        "vram_required":    size_gb,
                        "size_gb":          size_gb,
                        "speed_category":   "medium",
                        "context_window":   0,
                        "capabilities":     ["instruction following"],
                        "use_cases":        ["general chat"],
                        "tags":             tags,
                        "description":      f"Locally installed via Ollama. Size: {size_gb} GB",
                        "source":           "ollama",
                        "category":         categorize_model(name, tags),
                    })
                    known_names.add(name)
    except Exception:
        pass  # Ollama offline — silently skip

    return registry


def _print_banner():
    """Render the AIHub welcome banner."""
    console.print()
    console.print(Panel(
        "[bold #7c3aed]AI[/bold #7c3aed][bold white]Hub[/bold white] [dim]0.1.4[/dim] — "
        "[dim]Your all-in-one local AI platform[/dim]\n"
        "[dim]Memory · History · Tool Calling · Hardware-Aware Model Browser[/dim]",
        border_style="#7c3aed",
        padding=(0, 2),
        expand=False
    ))
    console.print()


# ─── Interactive Main Loop ────────────────────────────────────────────────────

@app.callback()
def main(ctx: typer.Context):
    """AIHub main entrypoint. Launches interactive TUI if no subcommand given."""
    if ctx.invoked_subcommand is None:
        interactive_main()


def interactive_main():
    """Persistent interactive shell loop."""
    _print_banner()

    if not config.hardware_scan_completed:
        hardware_scan()
        config.hardware_scan_completed = True
        save_config(config)
        _pause()

    while True:
        console.print()
        console.print(Rule("[dim]Main Menu[/dim]", style="#555555"))
        try:
            action = questionary.select(
                "What would you like to do?",
                choices=[
                    questionary.Choice("🤖  Browse & Manage Models", value="models"),
                    questionary.Choice("📚  Chat History",            value="history"),
                    questionary.Choice("🧠  Memory Management",       value="memory"),
                    questionary.Choice("🖥️  Hardware Diagnostics",   value="hardware"),
                    questionary.Choice("⚙️  Configuration",          value="config"),
                    questionary.Separator(),
                    questionary.Choice("🚪  Exit",                    value="exit"),
                ],
                style=CUSTOM_STYLE,
                use_indicator=True
            ).ask()

            if action in ("exit", None):
                if LAST_MODEL_USED:
                    unload_model(LAST_MODEL_USED)
                console.print("\n[bold #a78bfa]Goodbye! ✨[/bold #a78bfa]\n")
                break
            elif action == "hardware":
                hardware_scan()
                _pause()
            elif action == "config":
                config_edit()
                _pause()
            elif action == "memory":
                interactive_memory_menu()
            elif action == "models":
                interactive_models_menu()
            elif action == "history":
                interactive_history_menu()

        except KeyboardInterrupt:
            if LAST_MODEL_USED:
                unload_model(LAST_MODEL_USED)
            console.print("\n[bold #a78bfa]Goodbye! ✨[/bold #a78bfa]\n")
            break


def _pause():
    """Wait for Enter key (cross-platform)."""
    try:
        input("\n[Press Enter to continue...]")
    except KeyboardInterrupt:
        pass


def interactive_memory_menu():
    """Manage global and model-specific memory."""
    from .memory import load_memory, save_memory
    
    while True:
        console.print()
        console.print(Rule("[bold #7c3aed]Memory Management[/bold #7c3aed]", style="#7c3aed"))
        
        status = "[green]Enabled[/green]" if config.global_memory_enabled else "[red]Disabled[/red]"
        console.print(f"Global Memory is currently: {status}")
        console.print()
        
        console.print(Panel(
            "[bold cyan]Memory Reference Commands (Use during chat):[/bold cyan]\n"
            "  [white]/memory[/white]               - View current memory\n"
            "  [white]/memory save <k> <v>[/white] - Save a key-value fact\n"
            "  [white]/addmemory[/white]            - Auto-extract and save chat context\n"
            "  [white]/memory clear[/white]         - Clear all memory for the current model",
            border_style="cyan"
        ))
        
        action = questionary.select(
            "Memory Options:",
            choices=[
                questionary.Choice("🔄  Toggle Global Memory", value="toggle"),
                questionary.Choice("📝  Edit Global Memory", value="edit_global"),
                questionary.Choice("🤖  Edit Model-Specific Memory", value="edit_model"),
                questionary.Separator(),
                questionary.Choice("← Back", value="back"),
            ],
            style=CUSTOM_STYLE,
            use_indicator=True
        ).ask()
        
        if action in ("back", None):
            break
            
        elif action == "toggle":
            config.global_memory_enabled = not config.global_memory_enabled
            save_config(config)
            status = "[green]Enabled[/green]" if config.global_memory_enabled else "[red]Disabled[/red]"
            console.print(f"[bold green]Global memory toggled to:[/bold green] {status}")
            
        elif action == "edit_global":
            mem = load_memory("global")
            edited = typer.edit(mem or "## Global Memory\n\nAdd user facts here.", extension=".md")
            if edited is not None:
                save_memory("global", edited)
                console.print("[bold green]Global memory saved.[/bold green]")
                
        elif action == "edit_model":
            registry = load_registry_models()
            chat_models = [m["name"] for m in registry if m.get("type") == "chat"]
            if not chat_models:
                console.print("[yellow]No chat models available.[/yellow]")
                continue
                
            selected = questionary.select("Select model:", choices=chat_models, style=CUSTOM_STYLE).ask()
            if selected:
                mem = load_memory(selected)
                edited = typer.edit(mem or f"## Memory for {selected}\n\nAdd facts here.", extension=".md")
                if edited is not None:
                    save_memory(selected, edited)
                    console.print(f"[bold green]Memory for {selected} saved.[/bold green]")


def interactive_models_menu():
    """
    Hardware-aware model browser (v0.1.4).
    - Installed models shown first (green)
    - Compatible models sorted by best-fit (closest to hw limit)
    - Incompatible models greyed out in a separate section
    - Optional category/capability filter before listing
    """
    while True:
        registry    = load_registry_models()
        local_sizes = get_local_model_sizes()
        local_names = set(local_sizes.keys())

        if not registry:
            console.print("[bold red]⚠  No models found.[/bold red]")
            return

        # Detect available hardware limit
        hw_ram = get_available_ram_gb()

        console.print()
        console.print(Rule("[bold #7c3aed]Browse & Manage Models[/bold #7c3aed]", style="#7c3aed"))
        console.print(
            f"  [dim]Hardware limit:[/dim] [bold cyan]{hw_ram:.1f} GB[/bold cyan]  "
            f"[dim]|[/dim]  [green]■[/green] [dim]Installed[/dim]  "
            f"[green]✔[/green] [dim]Compatible[/dim]  "
            f"[dim white]✘ Exceeds hardware[/dim white]"
        )
        console.print()

        # ── Optional quick filter ─────────────────────────────────────────────
        filter_choice = questionary.select(
            "Filter by category (or show All):",
            choices=[
                questionary.Choice("All Models",           value="all"),
                questionary.Choice("Small  (≤4 GB RAM)",   value="small"),
                questionary.Choice("Medium (4–8 GB RAM)",  value="medium"),
                questionary.Choice("Large  (8–16 GB RAM)", value="large"),
                questionary.Choice("XLarge (16+ GB RAM)",  value="xlarge"),
                questionary.Separator(),
                questionary.Choice("← Back to Main Menu",  value="back"),
            ],
            style=CUSTOM_STYLE,
            use_indicator=True,
        ).ask()

        if filter_choice in ("back", None):
            break

        # Apply category filter
        cat_max = {"small": 4, "medium": 8, "large": 16, "xlarge": 99999}
        cat_min = {"small": 0, "medium": 4, "large":  8, "xlarge":    16}
        if filter_choice != "all":
            registry = [
                m for m in registry
                if cat_min[filter_choice] < m.get("vram_required", 0) <= cat_max[filter_choice]
                or (filter_choice == "small" and m.get("vram_required", 0) == 0)  # API
            ]

        # ── Sort: installed first, then best-fit, then over-limit ──────────────
        installed_models = [m for m in registry if m["name"] in local_names]
        not_installed    = [m for m in registry if m["name"] not in local_names]

        compatible, incompatible = sort_models_for_hardware(not_installed, hw_ram)

        # ── Build choices list ────────────────────────────────────────────────
        choices = []

        if installed_models:
            choices.append(questionary.Separator("── ● Installed ─────────────────────────────────"))
            for m in sorted(installed_models, key=lambda x: x.get("vram_required", 0), reverse=True):
                choices.append(_make_model_choice(m, local_names, hw_ram, installed=True))

        if compatible:
            choices.append(questionary.Separator("── ✔ Compatible (best-fit first) ───────────────"))
            for m in compatible:
                choices.append(_make_model_choice(m, local_names, hw_ram, installed=False))

        if incompatible:
            choices.append(questionary.Separator("── ✘ Exceeds hardware (not recommended) ────────"))
            for m in incompatible:
                choices.append(_make_model_choice(m, local_names, hw_ram, installed=False, greyed=True))

        choices.append(questionary.Separator())
        choices.append(questionary.Choice(title="← Back", value="back"))

        target = questionary.select(
            "Select a model to view details or start chat:",
            choices=choices,
            style=CUSTOM_STYLE,
            use_indicator=True,
        ).ask()

        if target in ("back", None):
            continue  # Go back to filter menu, not main menu

        handle_model_action(target, local_names)
        local_sizes = get_local_model_sizes()
        local_names = set(local_sizes.keys())


def _make_model_choice(model: dict, local_names: set, hw_ram: float,
                       installed: bool = False, greyed: bool = False) -> questionary.Choice:
    """Build a formatted questionary.Choice for a model card line."""
    name = model["name"]
    vram = model.get("vram_required", 0)
    size_gb = model.get("size_gb", vram)
    speed_label = get_speed_label(model)
    badges = get_capability_badges(model, max_badges=3)
    badge_str = "  ".join(badges) if badges else ""
    source = model.get("source", "registry")
    is_api = model.get("url", "").startswith("api://")

    # RAM display
    if is_api:
        ram_str = "  API  "
    else:
        ram_str = f"{vram:>4.0f} GB"

    # Installed marker
    if installed:
        inst = "●"
        name_fmt = f"{name:<34}"
    elif greyed:
        inst = "✘"
        name_fmt = f"{name:<34}"
    else:
        inst = " "
        name_fmt = f"{name:<34}"

    src_badge = "[API]" if is_api else "[Loc]" if source == "ollama" else "[Reg]"

    line = f"{inst} {name_fmt}  {ram_str}  {speed_label:<14}  {badge_str}"
    return questionary.Choice(title=line, value=model)


def handle_model_action(model: dict, local_names: set):
    """Sub-menu of actions for a selected model. Chat/agentic models only (v0.1.4)."""
    installed = model["name"] in local_names
    is_api    = model.get("url", "").startswith("api://") or model.get("source") == "huggingface"
    source    = model.get("source", "registry")

    # ── Build model info panel ────────────────────────────────────────────────
    console.print()
    vram      = model.get("vram_required", 0)
    size_gb   = model.get("size_gb", vram)
    desc      = model.get("description", "No description available.")
    speed_lbl = get_speed_label(model)
    speed_col = get_speed_color(model)
    badges    = get_capability_badges(model)
    badge_str = "  ".join(badges) if badges else "[dim]No specific badges[/dim]"
    use_cases = ", ".join(model.get("use_cases", []) or [])
    ctx_win   = model.get("context_window", 0)
    category  = model.get("category", "General")

    # Fetch live context length if installed
    ctx_str = f"{ctx_win // 1024}k" if ctx_win else "?"
    if installed and not is_api:
        info = get_model_info(model["name"])
        live_ctx = info.get("context_length", 0)
        if live_ctx:
            ctx_str = f"{live_ctx // 1024}k"

    ram_info = "Cloud API" if is_api else f"{vram} GB RAM"
    size_info = "N/A" if is_api else f"{size_gb:.1f} GB on disk"

    installed_badge = "[bold green]● INSTALLED[/bold green]" if installed else "[dim]Not installed[/dim]"
    src_label = {"registry": "Registry", "ollama": "Ollama (local)", "huggingface": "HuggingFace"}.get(source, source)

    panel_content = (
        f"[bold white]{model['name']}[/bold white]  {installed_badge}  [dim]({src_label})[/dim]\n"
        f"[dim]─────────────────────────────────────────────────────[/dim]\n"
        f"[dim]{desc}[/dim]\n\n"
        f"  [dim]Size:[/dim]     [cyan]{size_info}[/cyan]\n"
        f"  [dim]RAM req.:[/dim]  [cyan]{ram_info}[/cyan]\n"
        f"  [dim]Speed:[/dim]    [{speed_col}]{speed_lbl}[/{speed_col}]\n"
        f"  [dim]Context:[/dim]  [cyan]{ctx_str}[/cyan]\n"
        f"  [dim]Category:[/dim] [bold cyan]{category}[/bold cyan]\n\n"
        f"  {badge_str}\n\n"
        f"  [dim]Use cases:[/dim] [#a78bfa]{use_cases}[/#a78bfa]"
    )
    border = "green" if installed else "#7c3aed"
    console.print(Panel(
        panel_content,
        border_style=border,
        title="[bold #7c3aed]Model Details[/bold #7c3aed]",
        padding=(0, 1)
    ))

    # ── Build actions ─────────────────────────────────────────────────────────
    actions = []
    actions.append(questionary.Choice("Start Chat", value="chat"))

    if not installed and not is_api:
        actions.append(questionary.Choice("Download Model (Ollama)", value="download"))

    if installed and not is_api:
        sessions = list_sessions(model["name"])
        if sessions:
            actions.append(questionary.Choice(
                f"📚  View History  ({len(sessions)} sessions)", value="history"
            ))

    actions.append(questionary.Separator())
    actions.append(questionary.Choice("← Back", value="back"))

    action = questionary.select(
        "Choose action:",
        choices=actions,
        style=CUSTOM_STYLE,
        use_indicator=True
    ).ask()

    if action in ("back", None):
        return

    if action == "download":
        _do_download(model["name"])

    elif action == "chat":
        if not installed and not is_api:
            if questionary.confirm("Model not downloaded. Download now?", style=CUSTOM_STYLE).ask():
                _do_download(model["name"])
            else:
                return
        run_chat_session(model["name"], is_api=is_api)

    elif action == "history":
        _show_model_history_menu(model["name"])


def _show_model_history_menu(model_name: str):
    """Display the history browser for a specific model from the model sub-menu."""
    sessions = list_sessions(model_name)
    if not sessions:
        console.print(f"[dim]No history found for {model_name}.[/dim]")
        return

    table = Table(
        title=f"[bold #7c3aed]📚 History: {model_name}[/bold #7c3aed]",
        box=box.ROUNDED, border_style="#555555",
        header_style="bold #a78bfa", show_lines=True
    )
    table.add_column("#",        width=3, justify="right")
    table.add_column("Date",     min_width=19)
    table.add_column("Messages", justify="right")
    table.add_column("Temp",     justify="right", style="cyan")
    for i, s in enumerate(sessions[:20], 1):
        table.add_row(str(i), s["start_time"][:19].replace("T", " "),
                      str(s["message_count"]), f"{s['temperature']:.1f}")
    console.print(table)

    choices = [
        questionary.Choice(
            f"{i}. {s['start_time'][:19].replace('T',' ')} ({s['message_count']} msgs)",
            value=s["filename"]
        )
        for i, s in enumerate(sessions[:20], 1)
    ]
    choices += [
        questionary.Separator(),
        questionary.Choice("← Back", value=None),
    ]
    selected = questionary.select(
        "Resume session or go back:",
        choices=choices, style=CUSTOM_STYLE
    ).ask()
    if selected:
        loaded = load_session(model_name, selected)
        if loaded:
            run_chat_session(model_name, is_api=False, initial_messages=loaded)


def interactive_history_menu():
    """Top-level history browser — pick a model, then browse its sessions."""
    console.print()
    console.print(Rule("[dim]Chat History Browser[/dim]", style="#555555"))

    # List all models that have history
    from .config import HISTORY_DIR

    if not os.path.exists(HISTORY_DIR):
        console.print("[dim]No chat history found yet.[/dim]")
        return

    model_dirs = [
        d for d in os.listdir(HISTORY_DIR)
        if os.path.isdir(os.path.join(HISTORY_DIR, d))
    ]
    if not model_dirs:
        console.print("[dim]No chat history found yet.[/dim]")
        return

    choices = [questionary.Choice(d, value=d) for d in sorted(model_dirs)]
    choices.append(questionary.Choice("← Back", value=None))

    model_dir_name = questionary.select(
        "Select a model to view history:",
        choices=choices, style=CUSTOM_STYLE
    ).ask()
    if not model_dir_name:
        return

    # Reconstruct model name from dir name (best effort — replace _ back to :)
    # We just use the dir name as-is since list_sessions uses it
    _show_model_history_menu(model_dir_name)


def _do_download(model_name: str):
    """Download a model via Ollama with a live progress display."""
    if not is_ollama_running():
        console.print("[bold red]⚠  Ollama is not running! Start it first.[/bold red]")
        return
    console.print(f"\n[bold cyan]⬇  Downloading[/bold cyan] [white]{model_name}[/white] via Ollama...\n")
    try:
        last_status = ""
        for chunk in pull_model_stream(model_name):
            if "error" in chunk:
                console.print(f"[bold red]Error: {chunk['error']}[/bold red]")
                return
            status    = chunk.get("status", "")
            completed = chunk.get("completed", 0)
            total     = chunk.get("total", 0)
            if status and status != last_status:
                if total:
                    pct = int(completed / total * 100)
                    bar = "█" * (pct // 5) + "░" * (20 - pct // 5)
                    console.print(f"  [{bar}] {pct:3d}%  {status}", end="\r")
                else:
                    console.print(f"  {status}  ", end="\r")
                last_status = status
        console.print(f"\n[bold green]✔  {model_name} downloaded successfully![/bold green]")
    except Exception as e:
        console.print(f"[bold red]Download failed: {e}[/bold red]")


# ─── Named Subcommands ────────────────────────────────────────────────────────

@app.command(name="chat")
def chat(
    model_name: str = typer.Argument(None, help="Model name to chat with"),
    context_length: int = typer.Option(None, "--context-length", "-c", help="Override default context window size (e.g. 4096)")
):
    """Open an interactive chat session with a model."""
    if not is_ollama_running():
        console.print("[bold red]⚠  Ollama is not running![/bold red]")
        raise typer.Exit(1)

    registry    = load_registry_models()
    local_names = set(get_local_model_sizes().keys())
    chat_models = [m for m in registry if m.get("type") == "chat"]

    if model_name:
        selected = model_name
    else:
        choices = []
        for m in chat_models:
            inst = "✔" if m["name"] in local_names else "✘"
            src  = m.get("source", "reg")[:3].upper()
            choices.append(questionary.Choice(
                f"{m['name']:<28} [{inst}] [{src}]", value=m["name"]
            ))
        selected = questionary.select("Select a model:", choices=choices,
                                      style=CUSTOM_STYLE).ask()

    if not selected:
        return

    is_api = any(
        m.get("url", "").startswith("api://") or m.get("source") == "huggingface"
        for m in chat_models if m["name"] == selected
    )
    if selected not in local_names and not is_api:
        if questionary.confirm(
            f"Model {selected!r} is not installed. Download now?",
            style=CUSTOM_STYLE
        ).ask():
            _do_download(selected)
        else:
            return
        
    global LAST_MODEL_USED
    LAST_MODEL_USED = selected
    run_chat_session(selected, is_api=is_api, context_length=context_length)
    # Automatically unload after session ends if using direct CLI command
    unload_model(selected)


@app.command(name="history")
def history_cmd(model_name: str = typer.Argument(..., help="Model name to view history for")):
    """Browse and resume saved chat sessions for a model."""
    sessions = list_sessions(model_name)
    if not sessions:
        console.print(f"[bold yellow]No history found for model: {model_name}[/bold yellow]")
        raise typer.Exit(0)

    table = Table(
        title=f"[bold #7c3aed]📚 History: {model_name}[/bold #7c3aed]",
        box=box.ROUNDED, border_style="#555555",
        header_style="bold #a78bfa", show_lines=True
    )
    table.add_column("#",        width=3, justify="right")
    table.add_column("Filename", style="dim")
    table.add_column("Date",     min_width=19)
    table.add_column("Messages", justify="right")
    table.add_column("Temp",     justify="right", style="cyan")

    for i, s in enumerate(sessions, 1):
        table.add_row(
            str(i),
            s["filename"],
            s["start_time"][:19].replace("T", " "),
            str(s["message_count"]),
            f"{s['temperature']:.1f}",
        )
    console.print(table)

    choices = [
        questionary.Choice(
            f"{i}. {s['start_time'][:19].replace('T',' ')} ({s['message_count']} msgs)",
            value=s["filename"]
        )
        for i, s in enumerate(sessions, 1)
    ]
    choices += [
        questionary.Separator(),
        questionary.Choice("Resume latest in new chat", value="resume_latest"),
        questionary.Choice("Exit", value=None),
    ]

    selected = questionary.select(
        "Action:", choices=choices, style=CUSTOM_STYLE
    ).ask()

    if selected == "resume_latest":
        run_chat_session(model_name)
    elif selected and selected != "resume_latest":
        # Show specific session content
        messages = load_session(model_name, selected)
        for msg in messages:
            role    = msg.get("role", "?")
            content = msg.get("content", "")
            if role == "system":
                continue
            color = "#7c3aed" if role == "user" else "white"
            console.print(f"[bold {color}]{role.capitalize()}:[/bold {color}] {content}")
            console.print()

        if questionary.confirm("Resume this session?", default=True, style=CUSTOM_STYLE).ask():
            run_chat_session(model_name, initial_messages=messages)


@app.command(name="models-list")
def models_list():
    """List all available models with tags and hardware compatibility."""
    registry    = load_registry_models()
    local_sizes = get_local_model_sizes()

    table = Table(
        title="[bold #7c3aed]AIHub 0.1.4 — Model Registry (Chat & Agentic)[/bold #7c3aed]",
        box=box.ROUNDED, border_style="#7c3aed",
        header_style="bold #a78bfa", show_lines=True
    )
    table.add_column("Src",    style="dim",        width=4)
    table.add_column("Type",   style="dim",        width=6)
    table.add_column("Name",   min_width=20)
    table.add_column("Size",   justify="right",    style="cyan")
    table.add_column("VRAM",   justify="right")
    table.add_column("HW",     justify="center")
    table.add_column("DL",     justify="center")
    table.add_column("Ctx",    justify="right",    style="cyan")
    table.add_column("Tags",   style="#a78bfa")

    for m in registry:
        compat    = score_hardware(m.get("vram_required", 0))
        installed = m["name"] in local_sizes
        hw_icon   = "[green]✔[/green]" if compat    else "[yellow]⚠[/yellow]"
        dl_icon   = "[green]✔[/green]" if installed  else "[red]✘[/red]"
        src       = m.get("source", "reg")[:3].upper()

        if installed:
            size_str = f"{local_sizes[m['name']]:.1f} GB"
        elif m.get("size_gb"):
            size_str = f"{m['size_gb']:.1f} GB"
        elif m.get("vram_required"):
            size_str = f"~{m['vram_required']} GB"
        else:
            size_str = "?"

        # Fetch context length for Ollama models
        ctx_str = "-"
        if src == "OLL" or installed:
            info = get_model_info(m["name"])
            c_len = info.get("context_length", 0)
            if c_len:
                ctx_str = f"{c_len//1024}k"

        m_name = m.get("name", "")
        if installed:
            m_name = f"[bold green]{m_name}[/bold green]"

        table.add_row(
            src,
            m.get("type", "?").upper(),
            m_name,
            size_str,
            f"{m.get('vram_required', '?')} GB",
            hw_icon,
            dl_icon,
            ctx_str,
            ", ".join(m.get("tags", [])),
        )
    console.print(table)


@app.command(name="models-download")
def models_download(name: str = typer.Argument(..., help="Model name to download via Ollama")):
    """Download and install a model via Ollama."""
    _do_download(name)


@app.command(name="hardware-scan")
def hardware_scan():
    """Detect full hardware spec and display a ranked recommendation table."""
    console.print()
    console.print(Rule("[bold #7c3aed]Hardware Diagnostics[/bold #7c3aed]", style="#7c3aed"))

    with console.status("[bold cyan]Scanning hardware...[/bold cyan]"):
        cpu    = get_cpu_info()
        ram    = get_ram_info()
        disk   = get_disk_info()
        gpu    = get_gpu_info()
        os_inf = get_os_info()

    hw_table = Table(show_header=False, box=box.SIMPLE, border_style="dim")
    hw_table.add_column("Component", style="bold #a78bfa", width=20)
    hw_table.add_column("Value",     style="white")

    hw_table.add_row("OS",   os_inf)
    hw_table.add_row("CPU",  f"{cpu['model']} ({cpu['cores_physical']}C / {cpu['cores_logical']}T)")
    hw_table.add_row("RAM",  f"{ram['available_gb']} GB free of {ram['total_gb']} GB  ({ram['percent_used']}% used)")
    hw_table.add_row("Disk", f"{disk['free_gb']} GB free of {disk['total_gb']} GB")
    hw_table.add_row("GPU",  f"{gpu['vendor']} — {gpu['model']}")
    hw_table.add_row("VRAM", f"{round(gpu['vram_free_mb']/1024,1)} GB free of {round(gpu['vram_total_mb']/1024,1)} GB")

    console.print(Panel(hw_table, title="[bold #7c3aed]System Info[/bold #7c3aed]", border_style="#7c3aed"))

    vram_gb = gpu["vram_total_mb"] / 1024
    if vram_gb < 4:
        console.print(Panel(
            "[yellow]Low VRAM detected (< 4 GB). Only very small models will run locally.[/yellow]",
            border_style="yellow"
        ))
    elif vram_gb >= 8:
        console.print(Panel(
            "[green]Your hardware can comfortably run 7B–8B models and agentic workflows.[/green]",
            border_style="green"
        ))


    registry     = load_registry_models()
    local_sizes  = get_local_model_sizes()
    local_names  = set(local_sizes.keys())
    hw_ram       = get_available_ram_gb()

    def _safe_float(val):
        try:
            return float(val)
        except (ValueError, TypeError):
            return 0.0

    # Filter: only models that fit within available hardware
    fitting = [
        m for m in registry
        if m.get("type") not in ("image", "video")
        and (
            _safe_float(m.get("vram_required", 0)) <= hw_ram
            or m.get("url", "").startswith("api://")
        )
    ]

    # Sort: installed first, then best-fit (highest VRAM that still fits)
    fitting_installed     = [m for m in fitting if m["name"] in local_names]
    fitting_not_installed = [m for m in fitting if m["name"] not in local_names]
    fitting_installed.sort(key=lambda x: _safe_float(x.get("vram_required", 0)), reverse=True)
    fitting_not_installed.sort(key=lambda x: _safe_float(x.get("vram_required", 0)), reverse=True)
    sorted_fitting = fitting_installed + fitting_not_installed

    console.print()
    console.print(
        f"  [dim]Hardware limit:[/dim] [bold cyan]{hw_ram:.1f} GB[/bold cyan]  —  "
        f"[bold green]{len(sorted_fitting)}[/bold green] [dim]models fit your hardware[/dim]"
        f"  ([dim]{len(fitting_installed)} installed[/dim])"
    )
    console.print()

    rec_table = Table(
        title=f"[bold #7c3aed]Models That Fit Your Hardware (≤ {hw_ram:.1f} GB)[/bold #7c3aed]",
        box=box.ROUNDED, border_style="#555555",
        header_style="bold #a78bfa", show_lines=True
    )
    rec_table.add_column("",             width=2)
    rec_table.add_column("Model",        min_width=24, style="bold white")
    rec_table.add_column("VRAM",         justify="right", width=8)
    rec_table.add_column("Speed",        justify="left",  width=14)
    rec_table.add_column("Context",      justify="right", width=8, style="cyan")
    rec_table.add_column("Capabilities", min_width=32,   style="dim cyan")

    for m in sorted_fitting:
        installed = m["name"] in local_names
        vram_val  = _safe_float(m.get("vram_required", 0))
        is_api    = m.get("url", "").startswith("api://")
        speed     = get_speed_label(m)
        badges    = get_capability_badges(m, max_badges=3)
        badge_str = "  ".join(badges) if badges else "—"
        ctx_win   = m.get("context_window", 0)
        ctx_str   = f"{ctx_win // 1024}k" if ctx_win else ("API" if is_api else "?")
        vram_str  = "API" if is_api else f"{vram_val:.0f} GB"
        inst_dot  = "[bold green]●[/bold green]" if installed else " "
        name_fmt  = f"[bold green]{m['name']}[/bold green]" if installed else m["name"]

        rec_table.add_row(inst_dot, name_fmt, vram_str, speed, ctx_str, badge_str)

    console.print(rec_table)


# Note: image-generate and video-generate commands removed in v0.1.4
# AIHub 0.1.4 focuses exclusively on chat and agentic (text-based) models.


@app.command(name="config")
def config_edit():
    """Show the configuration file path and current settings."""
    conf = load_config()
    console.print(Panel(
        f"[bold cyan]Config file:[/bold cyan] [white]{CONFIG_FILE}[/white]\n\n"
        f"[dim]{yaml.dump(conf.model_dump(), allow_unicode=True)}[/dim]",
        title="[bold #7c3aed]Configuration[/bold #7c3aed]",
        border_style="#7c3aed"
    ))
    console.print("[dim]To change settings, edit the file above in any text editor.[/dim]")
    console.print(f"[dim]Key settings: ollama_api_url, hf_api_token, tools_enabled[/dim]")


@app.command(name="tui")
def launch_tui():
    """Launch the full-screen Textual TUI interface."""
    from .tui import launch_tui as run_tui
    run_tui()


if __name__ == "__main__":
    app()
