"""MemoryModal — tabbed editor for global + per-model memory."""
from __future__ import annotations

from typing import Optional

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container
from textual.screen import ModalScreen
from textual.widgets import Button, Static, TabbedContent, TabPane, TextArea

from ...memory import clear_memory, load_memory, save_memory


class MemoryModal(ModalScreen):
    BINDINGS = [
        Binding("escape", "cancel", "Close", show=False),
        Binding("ctrl+s", "save", "Save", show=False),
    ]

    def __init__(self, model_name: Optional[str]) -> None:
        super().__init__()
        self.model_name = model_name

    def compose(self) -> ComposeResult:
        with Container():
            title = f"[b]Memory[/b]   [#6b6b73](Ctrl+S save · Esc close)[/#6b6b73]"
            yield Static(title, id="mem-title")
            with TabbedContent(initial="tab-global", id="mem-tabs"):
                with TabPane("Global", id="tab-global"):
                    yield TextArea(load_memory("global"), id="mem-global", language=None)
                if self.model_name and self.model_name != "(no model)":
                    with TabPane(self.model_name, id="tab-model"):
                        yield TextArea(load_memory(self.model_name), id="mem-model", language=None)
            yield Button("Save current tab", id="mem-save", variant="success")
            yield Button("Clear current tab", id="mem-clear", variant="error")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "mem-save":
            self.action_save()
        elif event.button.id == "mem-clear":
            self._clear_current()

    def action_save(self) -> None:
        tab_id = self.query_one("#mem-tabs", TabbedContent).active
        if tab_id == "tab-global":
            text = self.query_one("#mem-global", TextArea).text
            save_memory("global", text)
            self.notify("Global memory saved.", severity="information")
        elif tab_id == "tab-model" and self.model_name:
            text = self.query_one("#mem-model", TextArea).text
            save_memory(self.model_name, text)
            self.notify(f"Memory saved for {self.model_name}.", severity="information")

    def _clear_current(self) -> None:
        tab_id = self.query_one("#mem-tabs", TabbedContent).active
        if tab_id == "tab-global":
            clear_memory("global")
            self.query_one("#mem-global", TextArea).load_text("")
            self.notify("Global memory cleared.", severity="warning")
        elif tab_id == "tab-model" and self.model_name:
            clear_memory(self.model_name)
            self.query_one("#mem-model", TextArea).load_text("")
            self.notify(f"Memory cleared for {self.model_name}.", severity="warning")

    def action_cancel(self) -> None:
        self.dismiss(None)
