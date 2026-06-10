"""SlashSuggest — autocomplete popup that appears above the chat input.

Sits in the vertical layout between ChatLog and ChatInput, hidden by default.
Shows when the user types "/" and filters as they keep typing.
Up/Down navigate, Tab/Enter accept, Esc dismisses.
"""
from __future__ import annotations

from typing import List, Optional, Tuple

from textual.app import ComposeResult
from textual.message import Message
from textual.widget import Widget
from textual.widgets import Static


# All recognised slash commands with short descriptions.
COMMANDS: List[Tuple[str, str]] = [
    ("/new",              "Start a fresh chat (same model)"),
    ("/help",             "Show help & key bindings"),
    ("/model",            "Switch model"),
    ("/memory",           "Show saved memory"),
    ("/memory save",      "Save a fact  →  /memory save <key> <value>"),
    ("/memory clear",     "Delete all memory"),
    ("/memoryadd",        "Auto-extract facts from this chat → memory"),
    ("/history",          "Browse & resume past sessions"),
    ("/tools",            "List available agentic tools"),
    ("/clear",            "Clear chat context (keep system)"),
]


class SlashSuggest(Widget):
    """Compact slash-command autocomplete popup."""

    DEFAULT_CSS = ""

    # Emitted when the user accepts a suggestion.
    class Accepted(Message):
        def __init__(self, command: str) -> None:
            super().__init__()
            self.command = command

    def __init__(self) -> None:
        super().__init__(id="slash-suggest")
        self._items: List[Tuple[str, str]] = []
        self._highlighted: int = 0
        self._visible: bool = False

    def compose(self) -> ComposeResult:
        # Placeholder — items are mounted dynamically.
        yield Static("", id="ss-placeholder")

    # ── Public API ───────────────────────────────────────────────────────

    def update_query(self, query: str) -> None:
        """Show matching commands for `query` (should start with '/')."""
        q = query.lower().strip()
        if not q or q == "/":
            self._items = list(COMMANDS)
        else:
            self._items = [
                (cmd, desc) for cmd, desc in COMMANDS
                if cmd.startswith(q) or q in cmd
            ]
        self._highlighted = 0
        self._show(bool(self._items))

    def hide(self) -> None:
        self._show(False)

    def move_up(self) -> None:
        if self._items:
            self._highlighted = (self._highlighted - 1) % len(self._items)
            self._redraw()

    def move_down(self) -> None:
        if self._items:
            self._highlighted = (self._highlighted + 1) % len(self._items)
            self._redraw()

    def accept(self) -> Optional[str]:
        """Accept highlighted item; returns the command string or None."""
        if self._items and 0 <= self._highlighted < len(self._items):
            cmd = self._items[self._highlighted][0]
            self.post_message(SlashSuggest.Accepted(cmd))
            self.hide()
            return cmd
        return None

    @property
    def is_visible(self) -> bool:
        return self._visible

    # ── Internals ────────────────────────────────────────────────────────

    def _show(self, visible: bool) -> None:
        self._visible = visible
        self.display = visible
        if visible:
            self._redraw()

    def _redraw(self) -> None:
        try:
            placeholder = self.query_one("#ss-placeholder", Static)
        except Exception:
            return
        if not self._items:
            placeholder.update("")
            return
        max_show = 6
        lines: List[str] = []
        start = max(0, self._highlighted - max_show + 1)
        items_to_show = self._items[start: start + max_show]
        for i, (cmd, desc) in enumerate(items_to_show):
            abs_idx = start + i
            if abs_idx == self._highlighted:
                lines.append(
                    f"[b][#a855f7]▶ {cmd:<28}[/#a855f7][/b]  [#e6e6e6]{desc}[/#e6e6e6]"
                )
            else:
                lines.append(
                    f"  [#a8a8b0]{cmd:<28}[/#a8a8b0]  [#6b6b73]{desc}[/#6b6b73]"
                )
        if len(self._items) > max_show:
            lines.append(
                f"  [#6b6b73]… {len(self._items) - max_show} more[/#6b6b73]"
            )
        placeholder.update("\n".join(lines))
