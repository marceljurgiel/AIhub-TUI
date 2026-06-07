"""Message bubbles for the AIHub chat log.

Three bubble flavours: user, assistant, system. All wrap a Markdown widget
so code fences render with syntax highlighting once the stream completes.
While a stream is in flight, the assistant bubble shows raw text via Static
to avoid pygments-per-token overhead, then swaps to Markdown when locked.
"""
from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widget import Widget
from textual.widgets import Markdown, Static


class BubbleBase(Vertical):
    """Shared base — handles role glyph + body container."""

    DEFAULT_CLASSES = ""
    ROLE_LABEL: str = ""
    ROLE_GLYPH: str = "›"

    def __init__(self, content: str = "", *, classes: str = "") -> None:
        super().__init__(classes=classes or self.DEFAULT_CLASSES)
        self._content = content
        self._body: Widget | None = None
        self._streaming = False

    HEADER_COLOR: str = "#a855f7"  # accent

    def compose(self) -> ComposeResult:
        glyph = self.ROLE_GLYPH
        label = self.ROLE_LABEL
        header = Static(
            f"[b][{self.HEADER_COLOR}]{glyph}[/{self.HEADER_COLOR}] {label}[/b]",
            classes="role-glyph",
        )
        header.styles.height = 1
        yield header
        body = Static(self._content)
        body.styles.height = "auto"
        self._body = body
        yield body

    # ── Streaming API used by ChatLog ─────────────────────────────────────
    def begin_streaming(self) -> None:
        self._streaming = True
        self._content = ""
        if self._body is not None:
            self._body.update("")

    def append(self, delta: str) -> None:
        self._content += delta
        if self._body is not None:
            self._body.update(self._content)

    def finalize_stream(self) -> None:
        """Mark streaming complete. Swap to a Markdown widget if the content
        looks like it benefits (contains a code fence or list).

        NB: do NOT name this `lock` — `Widget.lock` is an RLock attribute on
        the parent class.
        """
        self._streaming = False
        if self._body is not None and self._looks_like_markdown(self._content):
            try:
                md = Markdown(self._content)
                md.styles.height = "auto"
                self._body.remove()
                self.mount(md)
                self._body = md
            except Exception:
                pass

    @staticmethod
    def _looks_like_markdown(text: str) -> bool:
        return "```" in text or text.lstrip().startswith(("- ", "* ", "1. ", "# "))


class UserBubble(BubbleBase):
    ROLE_LABEL = "You"
    ROLE_GLYPH = "›"
    HEADER_COLOR = "#a855f7"


class AssistantBubble(BubbleBase):
    ROLE_LABEL = "AIHub"
    ROLE_GLYPH = "●"
    HEADER_COLOR = "#a8a8b0"


class SystemBubble(BubbleBase):
    ROLE_LABEL = "system"
    ROLE_GLYPH = "·"
    HEADER_COLOR = "#6b6b73"
