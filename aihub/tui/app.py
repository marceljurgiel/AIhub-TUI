"""AIHubApp — top-level Textual app.

Single persistent screen (ChatScreen); modals are pushed by bindings.
"""
from __future__ import annotations

from pathlib import Path

from textual.app import App

from .chat_screen import ChatScreen


class AIHubApp(App):
    CSS_PATH = "app.tcss"
    TITLE = "aihub"
    SUB_TITLE = "local AI"
    # Disable Textual's built-in Ctrl+P palette so our CommandPaletteModal owns it.
    ENABLE_COMMAND_PALETTE = False

    def on_mount(self) -> None:
        self.push_screen(ChatScreen())
