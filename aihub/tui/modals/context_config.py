"""ContextConfigModal — pick context length when starting a chat."""
from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Static

from ...config import config
from ...hardware import estimate_kv_cache_gb


class ContextConfigModal(ModalScreen[int]):
    """Asks for a context length. Returns int on Enter, None on Esc."""

    BINDINGS = [
        Binding("escape", "cancel", "Cancel", show=False),
        Binding("enter", "submit", "OK", show=False),
    ]

    def __init__(self, model_name: str, default_ctx: int | None = None) -> None:
        super().__init__()
        self.model_name = model_name
        self.default_ctx = default_ctx or config.default_context_length

    def compose(self) -> ComposeResult:
        with Container():
            yield Static(f"[b]Context length — {self.model_name}[/b]", id="ctx-title")
            yield Static(self._hint(self.default_ctx), id="ctx-hint")
            yield Input(value=str(self.default_ctx), id="ctx-input")
            with Horizontal(id="ctx-buttons"):
                yield Button("OK", id="ctx-ok", variant="success")
                yield Button("Cancel", id="ctx-cancel")

    def on_mount(self) -> None:
        self.query_one("#ctx-input", Input).focus()

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "ctx-input":
            try:
                v = int(event.value)
            except ValueError:
                self.query_one("#ctx-hint", Static).update("[#ff6e6e]Must be an integer.[/#ff6e6e]")
                return
            self.query_one("#ctx-hint", Static).update(self._hint(v))

    def _hint(self, ctx: int) -> str:
        try:
            gb = estimate_kv_cache_gb(ctx, self.model_name)
        except Exception:
            gb = 0
        return f"[#6b6b73]≈ {gb} GB VRAM for KV cache[/#6b6b73]"

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "ctx-cancel":
            self.dismiss(None)
        elif event.button.id == "ctx-ok":
            self.action_submit()

    def action_submit(self) -> None:
        try:
            v = int(self.query_one("#ctx-input", Input).value)
        except ValueError:
            return
        self.dismiss(max(256, v))

    def action_cancel(self) -> None:
        self.dismiss(None)
