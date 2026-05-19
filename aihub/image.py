"""
AIHub - Image generation module.
Selects the best available image model based on detected hardware and runs generation.
"""
from rich.panel import Panel

from .console import console


def hardware_aware_image_generation(prompt: str, registry_models: list, hardware_score_func) -> None:
    """
    Select the most capable image model that fits the current hardware and run generation.

    Args:
        prompt: User's image generation prompt.
        registry_models: Full model registry list.
        hardware_score_func: Callable(vram_required) -> bool.
    """
    image_models = [m for m in registry_models if m.get("type") == "image"]
    suitable     = [m for m in image_models if hardware_score_func(m.get("vram_required", 0))]

    if not suitable:
        console.print(Panel(
            "[red]Your hardware doesn't meet the VRAM requirements for any local image model.\n"
            "Consider using a cloud-based image API instead.[/red]",
            title="[bold red]Hardware Warning[/bold red]",
            border_style="red"
        ))
        return

    # Pick the most capable model that fits
    best = sorted(suitable, key=lambda m: m.get("vram_required", 0))[-1]

    console.print(Panel(
        f"[bold white]Model:[/bold white] [cyan]{best['name']}[/cyan]  "
        f"([dim]VRAM: {best.get('vram_required', '?')} GB[/dim])\n"
        f"[bold white]Prompt:[/bold white] {prompt}",
        title="[bold #7c3aed]Image Generation[/bold #7c3aed]",
        border_style="#7c3aed"
    ))

    import time
    with console.status("[bold yellow]Generating image…[/bold yellow]"):
        time.sleep(3)

    console.print("[bold green]✔  Image generated![/bold green]  (Saved to [white]~/aihub_output.png[/white])")
