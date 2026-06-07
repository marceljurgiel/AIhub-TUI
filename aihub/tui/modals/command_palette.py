"""CommandPaletteModal — fuzzy action search.

Returns the selected action id (string) or None on cancel. ChatScreen
dispatches the action.
"""
from __future__ import annotations

from typing import List, Optional, Tuple

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container
from textual.screen import ModalScreen
from textual.widgets import Input, OptionList, Static
from textual.widgets.option_list import Option


ACTIONS: List[Tuple[str, str]] = [
    ("model_picker",      "Change model"),
    ("clear_chat",        "Clear chat (keep system)"),
    ("new_chat",          "New chat (same model)"),
    ("save_session",      "Save session now"),
    ("history",           "Browse history"),
    ("memory",            "Edit memory"),
    ("memoryadd_chat",    "Extract memory → model"),
    ("memoryadd_global",  "Extract memory → global"),
    ("hardware",          "Hardware info"),
    ("settings",          "Settings"),
    ("toggle_tools",      "Toggle tool calling"),
    ("help",              "Help"),
    ("quit",              "Quit"),
]


def _score(query: str, label: str) -> int:
    """Tiny fuzzy: every query character must appear in label in order.
    Score = -(span length); lower (more negative) is better; returns None on miss."""
    q = query.lower()
    s = label.lower()
    i = 0
    first = -1
    last = -1
    for j, ch in enumerate(s):
        if i < len(q) and ch == q[i]:
            if first < 0:
                first = j
            last = j
            i += 1
    if i < len(q):
        return -10_000  # miss
    return -(last - first)


class CommandPaletteModal(ModalScreen[Optional[str]]):
    BINDINGS = [
        Binding("escape", "cancel", "Close", show=False),
    ]

    def compose(self) -> ComposeResult:
        with Container():
            yield Static(
                "[b]Command palette[/b]   [#6b6b73](Esc to close)[/#6b6b73]",
                id="cp-title",
            )
            yield Input(placeholder="Type to fuzzy-search…", id="cp-search")
            yield OptionList(
                *[Option(label, id=aid) for aid, label in ACTIONS],
                id="cp-list",
            )

    def on_mount(self) -> None:
        try:
            self.query_one("#cp-search", Input).focus()
        except Exception:
            pass

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id != "cp-search":
            return
        q = event.value.strip()
        olist = self.query_one("#cp-list", OptionList)
        olist.clear_options()
        if not q:
            olist.add_options([Option(label, id=aid) for aid, label in ACTIONS])
            return
        scored = []
        for aid, label in ACTIONS:
            s = _score(q, label)
            if s > -10_000:
                scored.append((s, aid, label))
        scored.sort(key=lambda t: -t[0])  # higher (less negative) score first
        if not scored:
            olist.add_options([Option("(no match)", id="__none__", disabled=True)])
            return
        olist.add_options([Option(label, id=aid) for _, aid, label in scored])

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id != "cp-search":
            return
        # If there's exactly one match or the user pressed Enter, pick the
        # first visible option.
        olist = self.query_one("#cp-list", OptionList)
        try:
            first = olist.get_option_at_index(0)
        except Exception:
            first = None
        if first is None or first.id == "__none__":
            return
        self.dismiss(first.id)

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        if event.option_id and event.option_id != "__none__":
            self.dismiss(event.option_id)

    def action_cancel(self) -> None:
        self.dismiss(None)
