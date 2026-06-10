"""ModelChooserModal — pick a model NAME (string) from recent / installed / API."""
from __future__ import annotations

from typing import Optional

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container
from textual.screen import ModalScreen
from textual.widgets import OptionList, Static
from textual.widgets.option_list import Option


class ModelChooserModal(ModalScreen[Optional[str]]):
    """Returns the chosen model name (str), or None on cancel."""

    BINDINGS = [Binding("escape", "cancel", "Close", show=False)]

    def compose(self) -> ComposeResult:
        with Container(id="mc-container"):
            yield Static(
                "[b][#a855f7]Choose a model[/#a855f7][/b]   "
                "[#6b6b73]Enter select · Esc close[/#6b6b73]",
                id="mc-title",
            )
            yield OptionList(*self._build_options(), id="mc-list")

    def _build_options(self) -> list:
        from ...config import config
        opts: list = []
        seen: set = set()

        def add(name: str, suffix: str = "") -> None:
            if not name or name in seen:
                return
            seen.add(name)
            opts.append(Option(f"{name}{suffix}", id=name))

        # Recent
        recents = list(config.recent_models or [])
        if recents:
            opts.append(Option("[#6b6b73]── recent ──[/#6b6b73]", disabled=True))
            for n in recents:
                add(n)

        # Installed (Ollama)
        try:
            from ...ollama_client import get_local_model_sizes, is_ollama_running
            installed = sorted(get_local_model_sizes().keys()) if is_ollama_running() else []
        except Exception:
            installed = []
        if installed:
            opts.append(Option("[#6b6b73]── installed ──[/#6b6b73]", disabled=True))
            for n in installed:
                add(n)

        # Cloud API
        try:
            from ...api_models import get_api_models
            apis = get_api_models()
        except Exception:
            apis = []
        if apis:
            opts.append(Option("[#6b6b73]── cloud API ──[/#6b6b73]", disabled=True))
            for m in apis:
                add(m.get("api_model", ""), f"  [#6b6b73]{m.get('provider','')}[/#6b6b73]")

        if not seen:
            opts = [Option("(no models found — type the name instead)",
                           id="__none__", disabled=True)]
        return opts

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        if event.option_id and event.option_id != "__none__":
            self.dismiss(event.option_id)

    def action_cancel(self) -> None:
        self.dismiss(None)
