"""Sidebar — left nav with logo, current model, shortcut-keyed nav, version.

Nav items dispatch action names directly to ChatScreen — no simulate_key,
so clicking always works regardless of terminal key mappings.
"""
from __future__ import annotations

from rich.table import Table
from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Vertical, VerticalScroll
from textual.message import Message
from textual.widget import Widget
from textual.widgets import Static

from ... import __version__ as _VERSION


# ASCII art logo — figlet "standard" font, vertical purple gradient.
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

# (action_name, label, key_hint)
NAV_ITEMS = [
    ("new_chat",        "New Chat",  "^N"),
    ("agent",           "Agent",     "^G"),
    ("model_picker",    "Models",    "^O"),
    ("history",         "History",   "^R"),
    ("memory",          "Memory",    "^E"),
    ("hardware",        "Hardware",  "^B"),
    ("settings",        "Settings",  "^,"),
    ("command_palette", "Palette",   "^P"),
    ("help",            "Help",      "F1"),
]


class ClickableModel(Static):
    """The current-model line — click to open the model picker."""

    def on_click(self) -> None:
        self.post_message(NavItem.Pressed("model_picker"))


class NavItem(Static):
    """A clickable sidebar nav entry: label left, shortcut key right."""

    class Pressed(Message):
        def __init__(self, action_name: str) -> None:
            super().__init__()
            self.action_name = action_name

    def __init__(self, action_name: str, label: str, key: str,
                 active: bool = False) -> None:
        super().__init__("", classes="nav-item")
        self._action_name = action_name
        self._label = label
        self._key = key
        if active:
            self.add_class("-active")

    def render(self):
        active = self.has_class("-active")
        marker = "[#a855f7]▎[/#a855f7]" if active else " "
        icon = "[#a855f7]◆[/#a855f7]" if active else "[#6b6b73]◆[/#6b6b73]"
        lab_col = "#e6e6e6" if active else "#a8a8b0"
        t = Table.grid(expand=True, padding=0)
        t.add_column(justify="left", ratio=1, no_wrap=True)
        t.add_column(justify="right", no_wrap=True)
        t.add_row(
            Text.from_markup(f"{marker} {icon}  [{lab_col}]{self._label}[/{lab_col}]"),
            Text.from_markup(f"[#6b6b73]{self._key}[/#6b6b73] "),
        )
        return t

    def set_active(self, active: bool) -> None:
        self.set_class(active, "-active")
        self.refresh()

    def on_click(self) -> None:
        self.post_message(NavItem.Pressed(self._action_name))


class Sidebar(Widget):
    DEFAULT_CSS = ""

    def compose(self) -> ComposeResult:
        with Vertical(id="sidebar-inner"):
            yield Static(LOGO, id="sidebar-logo")
            yield ClickableModel(
                "  [#6b6b73]● no model — click to choose[/#6b6b73]\n"
                "  [#6b6b73]DISCONNECTED[/#6b6b73]",
                id="sidebar-model",
            )
            with VerticalScroll(id="sidebar-nav"):
                for i, (action_name, label, key) in enumerate(NAV_ITEMS):
                    yield NavItem(action_name, label, key, active=(i == 0))
            footer = Table.grid(expand=True, padding=0)
            footer.add_column(justify="left", ratio=1, no_wrap=True)
            footer.add_column(justify="right", no_wrap=True)
            footer.add_row(
                Text.from_markup(f" [#6b6b73]aihub v{_VERSION}[/#6b6b73]"),
                Text.from_markup("[#6b6b73]⌘K palette[/#6b6b73] "),
            )
            yield Static(footer, id="sidebar-version")

    def update_model(self, model_name: str, context_length: int,
                     online: bool = True) -> None:
        ctx = f"{context_length // 1024}K" if context_length >= 1024 else str(context_length)
        short = model_name if len(model_name) <= 30 else model_name[:29] + "…"
        dot = "[#22c55e]●[/#22c55e]" if online else "[#6b6b73]●[/#6b6b73]"
        conn = "[#22c55e]CONNECTED[/#22c55e]" if online else "[#6b6b73]OFFLINE[/#6b6b73]"
        try:
            self.query_one("#sidebar-model", Static).update(
                f"  {dot} [b][#a855f7]{short}[/#a855f7][/b]\n"
                f"  {conn} [#2a2a30]·[/#2a2a30] [#6b6b73]{ctx} CTX[/#6b6b73]"
            )
        except Exception:
            pass

    def on_nav_item_pressed(self, message: NavItem.Pressed) -> None:
        try:
            screen = self.app.screen
            action_fn = getattr(screen, f"action_{message.action_name}", None)
            if action_fn:
                action_fn()
        except Exception:
            pass
