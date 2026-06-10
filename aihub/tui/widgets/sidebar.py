"""Sidebar — left nav with ASCII logo, current model, and nav buttons.

Nav items dispatch action names directly to ChatScreen — no simulate_key,
so clicking always works regardless of terminal key mappings.
"""
from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Vertical, VerticalScroll
from textual.message import Message
from textual.widget import Widget
from textual.widgets import Static


# ASCII art logo — figlet "standard" font, vertical purple gradient
# (light lavender at the top → deep violet at the bottom).
_ART_LINES = [
    "  ,---.  ,--.,--.             ,--.  ",
    " /  O  \\ |  ||  ,---. ,--.,--.|  |-.",
    "|  .-.  ||  ||  .-.  ||  ||  || .-. '",
    "|  | |  ||  ||  | |  |'  ''  '| `-' |",
    "`--' `--'`--'`--' `--' `----'  `---' ",
]
_GRADIENT = ["#e9d5ff", "#c084fc", "#a855f7", "#9333ea", "#7e22ce"]
LOGO = "\n".join(
    f"[{_GRADIENT[i % len(_GRADIENT)]}]{line}[/{_GRADIENT[i % len(_GRADIENT)]}]"
    for i, line in enumerate(_ART_LINES)
)

# (label, action_name, key_hint)
NAV_ITEMS = [
    ("new_chat",        "  ◈  New Chat",  "C-n"),
    ("agent",           "  ◈  Agent",     "C-g"),
    ("model_picker",    "  ◈  Models",    "C-o"),
    ("history",         "  ◈  History",   "C-r"),
    ("memory",          "  ◈  Memory",    "C-e"),
    ("hardware",        "  ◈  Hardware",  "C-b"),
    ("settings",        "  ◈  Settings",  "C-,"),
    ("command_palette", "  ◈  Palette",   "C-p"),
    ("help",            "  ◈  Help",      "F1"),
]


class NavItem(Static):
    """A clickable sidebar nav entry that dispatches a named action."""

    class Pressed(Message):
        def __init__(self, action_name: str) -> None:
            super().__init__()
            self.action_name = action_name

    def __init__(self, action_name: str, label: str) -> None:
        super().__init__(label, classes="nav-item")
        self._action_name = action_name

    def on_click(self) -> None:
        self.post_message(NavItem.Pressed(self._action_name))


class Sidebar(Widget):
    DEFAULT_CSS = ""

    def compose(self) -> ComposeResult:
        with Vertical(id="sidebar-inner"):
            yield Static(LOGO, id="sidebar-logo")
            yield Static("  [#6b6b73]no model[/#6b6b73]", id="sidebar-model")
            yield Static("  [#2a2a30]──────────────────[/#2a2a30]", id="sidebar-sep")
            # Scrollable so every menu item stays reachable on short terminals.
            with VerticalScroll(id="sidebar-nav"):
                for action_name, label, _hint in NAV_ITEMS:
                    yield NavItem(action_name, label)

    def update_model(self, model_name: str, context_length: int) -> None:
        ctx = f"{context_length // 1024}k" if context_length >= 1024 else str(context_length)
        short = model_name if len(model_name) <= 36 else model_name[:35] + "…"
        try:
            self.query_one("#sidebar-model", Static).update(
                f"  [b][#a855f7]{short}[/#a855f7][/b]\n  [#6b6b73]ctx {ctx}[/#6b6b73]"
            )
        except Exception:
            pass

    def on_nav_item_pressed(self, message: NavItem.Pressed) -> None:
        # Find ChatScreen in the screen stack and call its action directly.
        # This avoids simulate_key which maps ctrl+m→enter, ctrl+h→backspace etc.
        try:
            screen = self.app.screen
            action_fn = getattr(screen, f"action_{message.action_name}", None)
            if action_fn:
                action_fn()
        except Exception:
            pass
