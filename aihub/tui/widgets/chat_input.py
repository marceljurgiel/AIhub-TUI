"""ChatInput — multi-line TextArea with prompt history and slash autocomplete.

Bindings:
  Enter      submit (or accept slash suggestion if popup is open)
  Ctrl+J     insert newline
  Up/Down    navigate slash suggestions (popup open) or recall prompt history (empty)
  Tab        accept highlighted slash suggestion
  Esc        dismiss slash popup (then normal Esc behaviour)
"""
from __future__ import annotations

from collections import deque
from typing import Deque, Optional

from textual import events
from textual.binding import Binding
from textual.widgets import TextArea

from ..messages import InputSubmitted, SlashNavigate, SlashQuery


class ChatInput(TextArea):
    BINDINGS = [
        Binding("enter", "submit", "Submit", priority=True, show=False),
        Binding("ctrl+j", "newline", "Newline", show=False),
    ]

    def __init__(self) -> None:
        super().__init__(text="", language=None, show_line_numbers=False)
        # NOTE: do NOT name this `history` — TextArea uses that for its undo stack.
        self.prompt_history: Deque[str] = deque(maxlen=100)
        self._history_pos: Optional[int] = None
        self._slash_popup_open: bool = False      # set by ChatScreen
        self._accepting_suggestion: bool = False  # suppresses spurious SlashQuery during load_text

    # ── Public actions ────────────────────────────────────────────────────

    def action_submit(self) -> None:
        # If the slash popup is open, Enter accepts the suggestion instead.
        if self._slash_popup_open:
            self.post_message(SlashNavigate("enter"))
            return
        text = self.text.strip()
        if not text:
            return
        if not self.prompt_history or self.prompt_history[0] != text:
            self.prompt_history.appendleft(text)
        self._history_pos = None
        self.post_message(InputSubmitted(text))
        self.clear()

    def action_newline(self) -> None:
        self.insert("\n")

    # ── Key handling ──────────────────────────────────────────────────────

    def on_key(self, event: events.Key) -> None:
        # Delegate navigation keys to the slash popup when it's open.
        if self._slash_popup_open:
            if event.key in ("up", "down", "tab", "escape"):
                event.prevent_default()
                event.stop()
                self.post_message(SlashNavigate(event.key))
                return

        # Prompt history: Up/Down when input is empty and no popup.
        if event.key == "up" and not self.text and self.prompt_history:
            event.prevent_default()
            event.stop()
            self._history_pos = 0 if self._history_pos is None else min(
                self._history_pos + 1, len(self.prompt_history) - 1
            )
            self.load_text(self.prompt_history[self._history_pos])
        elif event.key == "down" and self.prompt_history and self._history_pos is not None:
            event.prevent_default()
            event.stop()
            self._history_pos -= 1
            if self._history_pos < 0:
                self._history_pos = None
                self.load_text("")
            else:
                self.load_text(self.prompt_history[self._history_pos])

    # ── Text change → slash popup trigger ────────────────────────────────

    def on_text_area_changed(self, event: TextArea.Changed) -> None:
        text = self.text
        if text.startswith("/"):
            self.post_message(SlashQuery(text))
        elif self._slash_popup_open:
            # User deleted the "/" — close the popup.
            self.post_message(SlashQuery(""))
