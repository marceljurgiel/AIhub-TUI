"""PermissionModal — approve/deny a mutating agent action (Plan mode)."""
from __future__ import annotations

import json
from typing import Any, Dict

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal
from textual.screen import ModalScreen
from textual.widgets import Button, Static


_LABELS = {
    "run_terminal": "run a shell command",
    "write_file":   "write a file",
    "edit_file":    "edit a file",
}


class PermissionModal(ModalScreen[bool]):
    """Returns True (allow) or False (deny)."""

    BINDINGS = [
        Binding("escape", "deny", "Deny", show=False),
        Binding("y", "allow", "Allow", show=False),
        Binding("n", "deny", "Deny", show=False),
    ]

    def __init__(self, tool: str, args: Dict[str, Any]) -> None:
        super().__init__()
        self.tool = tool
        self.args = args or {}

    def _detail(self) -> str:
        if self.tool == "run_terminal":
            return self.args.get("command", "")
        if self.tool in ("write_file", "edit_file"):
            path = self.args.get("path", "?")
            if self.tool == "edit_file":
                old = (self.args.get("old", "") or "")[:300]
                new = (self.args.get("new", "") or "")[:300]
                return f"{path}\n\n[#ff6e6e]- {old}[/#ff6e6e]\n[#22c55e]+ {new}[/#22c55e]"
            return f"{path}\n\n{(self.args.get('content','') or '')[:400]}"
        return json.dumps(self.args)[:400]

    def compose(self) -> ComposeResult:
        with Container(id="perm-container"):
            verb = _LABELS.get(self.tool, self.tool)
            yield Static(
                f"[b][#ffb454]Agent wants to {verb}[/#ffb454][/b]   "
                "[#6b6b73](Y allow · N/Esc deny)[/#6b6b73]",
                id="perm-title",
            )
            yield Static(self._detail(), id="perm-detail")
            with Horizontal(id="perm-buttons"):
                yield Button("Allow", id="perm-allow", variant="success")
                yield Button("Deny", id="perm-deny", variant="error")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "perm-allow")

    def action_allow(self) -> None:
        self.dismiss(True)

    def action_deny(self) -> None:
        self.dismiss(False)
