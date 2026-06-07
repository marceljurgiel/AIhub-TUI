"""
AIHub CLI - Main entrypoint (v0.2.0).

`aihub` launches the full-screen TUI. The non-interactive subcommands
(`chat`, `models-list`, `models-download`, `hardware-scan`, `history`,
`config`) remain for scripting / quick access.
"""
import json
import sys

import typer
import questionary
from questionary import Style
from rich.table import Table
from rich.panel import Panel
from rich.rule import Rule
from rich import box
import requests
import yaml

from .console import console
from .config import config, CONFIG_FILE, load_config, save_config
from .hardware import (
    get_gpu_info, get_cpu_info, get_ram_info, get_disk_info, get_os_info,
    score_hardware, estimate_tokens_per_sec, get_available_ram_gb,
)
from .ollama_client import (
    get_local_models, get_local_model_sizes, pull_model_stream,
    is_ollama_running, get_model_info, unload_model,
)
from .hf_client import fetch_hf_models, get_hf_error
from .chat_cli import run_chat_session
from .history import list_sessions, load_session, delete_session, get_history_dir
from .models import (
    categorize_model, get_capability_badges, get_speed_label, get_speed_color,
    sort_models_for_hardware, CATEGORIES,
)


app = typer.Typer(
    help="AIHub 0.2.0 — Your all-in-one local AI management platform.",
    invoke_without_command=True,
)
LAST_MODEL_USED = None  # tracks the most recent model for cleanup on exit

# ─── Questionary style (used by a couple of remaining one-shot confirms) ─────
CUSTOM_STYLE = Style([
    ("qmark",        "fg:#7c3aed bold"),
    ("question",     "fg:#ffffff bold"),
    ("answer",       "fg:#7c3aed bold"),
    ("pointer",      "fg:#7c3aed bold"),
    ("highlighted",  "fg:#7c3aed bold"),
    ("selected",     "fg:#a78bfa"),
    ("text",         "fg:#ffffff"),
])


def load_registry_models() -> list:
    """
    Build the full model list by merging two sources:
      1. Static JSON registry (models_registry.json) — chat/text models only.
      2. Live Ollama models from /api/tags.

    Image and video models are excluded entirely. Duplicates by name are
    deduplicated (registry wins).
    """
    registry = []

    try:
        with open(config.models_registry_path, "r", encoding="utf-8") as f:
            raw = json.load(f)
        for m in raw:
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


# ─── Main callback: launch TUI when no subcommand given ──────────────────────

@app.callback()
def main(ctx: typer.Context):
    """AIHub. Launches the TUI when no subcommand is given."""
    if ctx.invoked_subcommand is None:
        from .tui import run
        run()


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


# ─── Named subcommands ───────────────────────────────────────────────────────

@app.command(name="chat")
def chat(
    model_name: str = typer.Argument(None, help="Model name to chat with"),
    context_length: int = typer.Option(None, "--context-length", "-c", help="Override default context window size (e.g. 4096)"),
):
    """Open an interactive chat session with a model."""
    if not model_name:
        console.print("[bold red]Usage:[/bold red] [white]aihub chat <model>[/white]")
        console.print("[dim]Run [white]aihub[/white] (no subcommand) to pick a model in the TUI.[/dim]")
        raise typer.Exit(2)

    if not is_ollama_running():
        console.print("[bold red]⚠  Ollama is not running![/bold red]")
        raise typer.Exit(1)

    registry    = load_registry_models()
    local_names = set(get_local_model_sizes().keys())
    chat_models = [m for m in registry if m.get("type") == "chat"]

    selected = model_name

    is_api = any(
        m.get("url", "").startswith("api://") or m.get("source") == "huggingface"
        for m in chat_models if m["name"] == selected
    )
    if selected not in local_names and not is_api:
        if questionary.confirm(
            f"Model {selected!r} is not installed. Download now?",
            style=CUSTOM_STYLE,
        ).ask():
            _do_download(selected)
        else:
            return

    global LAST_MODEL_USED
    LAST_MODEL_USED = selected
    run_chat_session(selected, is_api=is_api, context_length=context_length)
    unload_model(selected)


@app.command(name="history")
def history_cmd(model_name: str = typer.Argument(..., help="Model name to view history for")):
    """List saved chat sessions for a model. (Resume via the TUI.)"""
    sessions = list_sessions(model_name)
    if not sessions:
        console.print(f"[bold yellow]No history found for model: {model_name}[/bold yellow]")
        raise typer.Exit(0)

    table = Table(
        title=f"[bold #7c3aed]📚 History: {model_name}[/bold #7c3aed]",
        box=box.ROUNDED, border_style="#555555",
        header_style="bold #a78bfa", show_lines=True,
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
    console.print("[dim]Resume a session from the TUI history modal (Ctrl+H).[/dim]")


@app.command(name="models-list")
def models_list():
    """List all available models with tags and hardware compatibility."""
    registry    = load_registry_models()
    local_sizes = get_local_model_sizes()

    table = Table(
        title="[bold #7c3aed]AIHub 0.2.0 — Model Registry (Chat & Agentic)[/bold #7c3aed]",
        box=box.ROUNDED, border_style="#7c3aed",
        header_style="bold #a78bfa", show_lines=True,
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
            border_style="yellow",
        ))
    elif vram_gb >= 8:
        console.print(Panel(
            "[green]Your hardware can comfortably run 7B–8B models and agentic workflows.[/green]",
            border_style="green",
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

    fitting = [
        m for m in registry
        if m.get("type") not in ("image", "video")
        and (
            _safe_float(m.get("vram_required", 0)) <= hw_ram
            or m.get("url", "").startswith("api://")
        )
    ]
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
        header_style="bold #a78bfa", show_lines=True,
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


@app.command(name="config")
def config_edit():
    """Show the configuration file path and current settings."""
    conf = load_config()
    console.print(Panel(
        f"[bold cyan]Config file:[/bold cyan] [white]{CONFIG_FILE}[/white]\n\n"
        f"[dim]{yaml.dump(conf.model_dump(), allow_unicode=True)}[/dim]",
        title="[bold #7c3aed]Configuration[/bold #7c3aed]",
        border_style="#7c3aed",
    ))
    console.print("[dim]To change settings, edit the file above in any text editor.[/dim]")
    console.print(f"[dim]Key settings: ollama_api_url, hf_api_token, tools_enabled[/dim]")


if __name__ == "__main__":
    app()
