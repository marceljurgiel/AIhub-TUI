"""MemoryModal — editor for the shared memory store."""
from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container
from textual.screen import ModalScreen
from textual.widgets import Button, Static, TextArea

from ...memory import clear_memory, load_memory, save_memory


class MemoryModal(ModalScreen):
    BINDINGS = [
        Binding("escape", "cancel", "Close", show=False),
        Binding("ctrl+s", "save", "Save", show=False),
    ]

    def compose(self) -> ComposeResult:
        with Container():
            yield Static(
                "[b]Memory[/b]   [#6b6b73](Ctrl+S save · Esc close)[/#6b6b73]",
                id="mem-title",
            )
            yield TextArea(load_memory(), id="mem-text", language=None)
            yield Button("Save", id="mem-save", variant="success")
            yield Button("Clear", id="mem-clear", variant="error")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "mem-save":
            self.action_save()
        elif event.button.id == "mem-clear":
            clear_memory()
            self.query_one("#mem-text", TextArea).load_text("")
            self.notify("Memory cleared.", severity="warning")

    def action_save(self) -> None:
        save_memory(self.query_one("#mem-text", TextArea).text)
        self.notify("Memory saved.", severity="information")

    def action_cancel(self) -> None:
        self.dismiss(None)
