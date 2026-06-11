"""ContextConfigModal — pick context length when starting a chat."""
from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Static

from ...config import config
from ...hardware import estimate_kv_cache_gb, free_vram_gb, recommend_context


class ContextConfigModal(ModalScreen[int]):
    """Asks for a context length. Returns int on Enter, None on Esc.

    Defaults to the largest context that fits the detected GPU VRAM (so the
    model stays on the GPU), and warns in red when a chosen value would spill
    the KV cache to CPU.
    """

    BINDINGS = [
        Binding("escape", "cancel", "Cancel", show=False),
        Binding("enter", "submit", "OK", show=False),
    ]

    def __init__(self, model_name: str, default_ctx: int | None = None) -> None:
        super().__init__()
        self.model_name = model_name
        # Cache VRAM + model size + max context once (these calls hit the GPU/
        # Ollama and shouldn't run on every keystroke in _hint()).
        self._free_vram = free_vram_gb()
        self._model_gb = 0.0
        max_ctx = None
        try:
            from ...ollama_client import get_local_model_sizes, get_model_info
            sizes = get_local_model_sizes()
            self._model_gb = sizes.get(model_name) or sizes.get(model_name + ":latest") or 0.0
            max_ctx = get_model_info(model_name).get("max_context") or None
        except Exception:
            pass
        self._max_ctx = max_ctx
        if default_ctx:
            self.default_ctx = default_ctx
        else:
            self.default_ctx = recommend_context(model_name, hard_cap=max_ctx)

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
            kv = estimate_kv_cache_gb(ctx, self.model_name)
        except Exception:
            kv = 0
        need = round(self._model_gb + kv, 1)
        base = f"≈ {kv} GB KV cache · ~{need} GB total"
        cap = ""
        if self._max_ctx and ctx > self._max_ctx:
            cap = f"  [#ffb454](model max is {self._max_ctx})[/#ffb454]"
        if self._free_vram <= 0:
            return f"[#6b6b73]{base} · CPU (no GPU detected)[/#6b6b73]{cap}"
        if need > self._free_vram:
            return (f"[#ff6e6e]⚠ {base} — exceeds {self._free_vram:.1f} GB free VRAM, "
                    f"will spill to CPU[/#ff6e6e]{cap}")
        return f"[#22c55e]{base} — fits GPU ({self._free_vram:.1f} GB free)[/#22c55e]{cap}"

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
