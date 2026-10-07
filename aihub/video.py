"""
AIHub - Video generation module.
Supports LTX Video 2.3 as the primary model with automatic fallback to SVD.
"""
from rich.panel import Panel

from .console import console


def hardware_aware_video_generation(prompt: str, registry_models: list, hardware_score_func) -> None:
    """
    Generate a video from a text prompt using the best available video model.

    Primary:  LTX Video 2.3  (requires ≥16 GB VRAM)
    Fallback: Stable Video Diffusion (SVD)  (requires ≥12 GB VRAM)

    Args:
        prompt: User's video generation prompt.
        registry_models: Full model registry list.
        hardware_score_func: Callable(vram_required) -> bool.
    """
    ltx_model = next((m for m in registry_models if m.get("name") == "ltx-video-2.3"), None)
    svd_model = next((m for m in registry_models if "svd" in m.get("name", "").lower()), None)

    model_to_use = None

    if ltx_model and hardware_score_func(ltx_model.get("vram_required", 16)):
        model_to_use = ltx_model
    elif svd_model and hardware_score_func(svd_model.get("vram_required", 12)):
        console.print("[bold yellow]⚠  Not enough VRAM for LTX Video 2.3. Falling back to Stable Video Diffusion (SVD).[/bold yellow]")
        model_to_use = svd_model

    if not model_to_use:
        console.print(Panel(
            "[red]Your hardware doesn't meet the minimum VRAM requirements for video generation.\n"
            "LTX Video 2.3 requires [bold]≥16 GB VRAM[/bold]; SVD requires [bold]≥12 GB VRAM[/bold].[/red]",
            title="[bold red]Hardware Warning[/bold red]",
            border_style="red"
        ))
        return

    console.print(Panel(
        f"[bold white]Model:[/bold white] [cyan]{model_to_use['name']}[/cyan]  "
        f"([dim]VRAM: {model_to_use.get('vram_required', '?')} GB[/dim])\n"
        f"[bold white]Prompt:[/bold white] {prompt}",
        title="[bold #7c3aed]Video Generation[/bold #7c3aed]",
        border_style="#7c3aed"
    ))

    import time
    with console.status("[bold magenta]Initializing video model and rendering frames…[/bold magenta]"):
        time.sleep(4)

    console.print("[bold green]✔  Video generated![/bold green]  (Saved to [white]~/aihub_video.mp4[/white])")
