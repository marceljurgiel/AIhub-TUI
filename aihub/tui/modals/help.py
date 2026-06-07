"""HelpModal — keybind cheatsheet + slash command reference."""
from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Static

from ...slash import HELP_TEXT


KEYBINDS = """\
[b]Bindings[/b]

  Ctrl+P    Command palette
  Ctrl+M    Model picker
  Ctrl+H    History
  Ctrl+E    Memory editor
  Ctrl+I    Hardware info
  Ctrl+,    Settings
  Ctrl+L    Clear chat (keep system)
  Ctrl+N    New chat (same model)
  Ctrl+S    Save session
  Ctrl+T    Toggle tool calling
  Ctrl+J    Insert newline (in input)
  Enter     Submit message
  Esc       Cancel streaming / close modal
  F1 / ?    This help
  Ctrl+Q    Quit
"""


class HelpModal(ModalScreen):
    BINDINGS = [
        Binding("escape", "close", "Close", show=False),
        Binding("q", "close", "Close", show=False),
        Binding("question_mark", "close", "Close", show=False),
    ]

    def compose(self) -> ComposeResult:
        with Container():
            yield Static("[b]AIHub — Help[/b]", id="help-title")
            with VerticalScroll():
                yield Static(KEYBINDS + "\n" + HELP_TEXT)

    def action_close(self) -> None:
        self.dismiss(None)
