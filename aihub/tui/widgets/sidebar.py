"""Sidebar — left nav with logo, current model, shortcut-keyed nav, version.

Nav items dispatch action names directly to ChatScreen — no simulate_key,
so clicking always works regardless of terminal key mappings.

Rendering note: Textual 8.x measures a Rich Table as zero-height, so nav rows
build a manually right-padded Rich Text in render() (the widget width is known
there) rather than a Table.grid.
"""
from __future__ import annotations

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

# (action_name, label, single-key shortcut)
NAV_ITEMS = [
    ("new_chat",        "New Chat",  "N"),
    ("agent",           "Agent",     "A"),
    ("model_picker",    "Models",    "M"),
    ("history",         "History",   "H"),
    ("memory",          "Memory",    "E"),
    ("hardware",        "Hardware",  "W"),
    ("settings",        "Settings",  "S"),
    ("command_palette", "Palette",   "P"),
    ("help",            "Help",      "?"),
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

    def render(self) -> Text:
        active = self.has_class("-active")
        width = max(int(self.size.width) or 0, 12)
        icon_col = "#a855f7" if active else "#6b6b73"
        lab_col = "#e6e6e6" if active else "#a8a8b0"
        left = Text()
        left.append("▎ " if active else "  ", style="#a855f7")
        left.append("◆  ", style=icon_col)
        left.append(self._label, style=lab_col)
        right = Text(self._key + " ", style="#6b6b73")
        pad = max(1, width - left.cell_len - right.cell_len)
        out = Text()
        out.append_text(left)
        out.append(" " * pad)
        out.append_text(right)
        return out

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
                "  [#6b6b73]●[/#6b6b73] [#6b6b73]no model — click to choose[/#6b6b73]\n"
                "  [#ff6e6e]OFFLINE[/#ff6e6e]",
                id="sidebar-model",
            )
            with VerticalScroll(id="sidebar-nav"):
                for i, (action_name, label, key) in enumerate(NAV_ITEMS):
                    yield NavItem(action_name, label, key, active=(i == 0))
            yield Static(
                f" [#6b6b73]aihub v{_VERSION}[/#6b6b73]  "
                f"[#2a2a30]·[/#2a2a30]  [#6b6b73]⌘K palette[/#6b6b73]",
                id="sidebar-version",
            )

    def update_model(self, model_name: str, context_length: int,
                     online: bool = True) -> None:
        """online=True (model chosen and backend working) → green CONNECTED;
        otherwise red OFFLINE."""
        ctx = f"{context_length // 1024}K" if context_length >= 1024 else str(context_length)
        short = model_name if len(model_name) <= 30 else model_name[:29] + "…"
        if online and model_name:
            dot = "[#22c55e]●[/#22c55e]"
            line1 = f"  {dot} [b][#a855f7]{short}[/#a855f7][/b]"
            line2 = f"  [#22c55e]CONNECTED[/#22c55e] [#2a2a30]·[/#2a2a30] [#6b6b73]{ctx} CTX[/#6b6b73]"
        else:
            dot = "[#ff6e6e]●[/#ff6e6e]"
            label = short if model_name else "no model — click to choose"
            line1 = f"  {dot} [#a8a8b0]{label}[/#a8a8b0]"
            line2 = f"  [#ff6e6e]OFFLINE[/#ff6e6e]"
        try:
            self.query_one("#sidebar-model", Static).update(f"{line1}\n{line2}")
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
