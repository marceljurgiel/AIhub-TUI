"""ChatLog — owns the live assistant bubble and the tool panels.

Streaming pattern: `append_assistant_text(delta)` buffers the delta and
schedules a single coalesced render per frame via `call_after_refresh`,
avoiding per-token widget.update() storms.

Autoscroll: only when the user is already within a few rows of the bottom,
so scrolling up to read mid-stream doesn't yank the viewport back.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from textual.containers import VerticalScroll

from .message_bubble import AssistantBubble, SystemBubble, UserBubble
from .tool_panel import ToolCallPanel


class ChatLog(VerticalScroll):
    """Stream-aware container for chat bubbles and tool panels."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._active_assistant: Optional[AssistantBubble] = None
        self._active_tool_panels: Dict[str, ToolCallPanel] = {}
        self._buffer: str = ""
        self._flush_scheduled = False

    # ── User-driven mutations ────────────────────────────────────────────

    def add_user(self, text: str) -> None:
        self._lock_active_assistant()
        bubble = UserBubble(text)
        self.mount(bubble)
        self._maybe_scroll_to_bottom()

    def add_system(self, text: str) -> None:
        self._lock_active_assistant()
        bubble = SystemBubble(text)
        self.mount(bubble)
        self._maybe_scroll_to_bottom()

    def clear_keeping_system(self) -> None:
        """Remove everything except SystemBubble (kept for memory hint, etc.)."""
        self._active_assistant = None
        self._active_tool_panels.clear()
        self._buffer = ""
        for child in list(self.children):
            if not isinstance(child, SystemBubble):
                child.remove()

    def clear_all(self) -> None:
        """Remove every bubble — a full reset of the visible log (used by New
        chat / Clear / model switch so old notices don't pile up)."""
        self._active_assistant = None
        self._active_tool_panels.clear()
        self._buffer = ""
        for child in list(self.children):
            child.remove()

    # ── Streaming assistant path ─────────────────────────────────────────

    def begin_assistant(self) -> None:
        self._lock_active_assistant()
        bubble = AssistantBubble("")
        bubble.begin_streaming()
        self.mount(bubble)
        self._active_assistant = bubble
        self._buffer = ""
        self._maybe_scroll_to_bottom()

    def append_assistant_text(self, delta: str) -> None:
        if self._active_assistant is None:
            self.begin_assistant()
        self._buffer += delta
        if not self._flush_scheduled:
            self._flush_scheduled = True
            self.app.call_after_refresh(self._flush_stream)

    def _flush_stream(self) -> None:
        self._flush_scheduled = False
        if self._active_assistant is not None and self._buffer:
            self._active_assistant.append(self._buffer)
            self._buffer = ""
            self._maybe_scroll_to_bottom()

    def end_assistant(self) -> None:
        # Drain remaining buffer before finalising the bubble.
        if self._active_assistant is not None:
            if self._buffer:
                self._active_assistant.append(self._buffer)
                self._buffer = ""
            self._active_assistant.finalize_stream()
            self._active_assistant = None

    # ── Tool panels ──────────────────────────────────────────────────────

    def start_tool_panel(
        self,
        call_id: str,
        name: str,
        arguments: Dict[str, Any],
    ) -> None:
        self.end_assistant()
        panel = ToolCallPanel(call_id, name, arguments)
        self.mount(panel)
        self._active_tool_panels[call_id] = panel
        self._maybe_scroll_to_bottom()

    def complete_tool_panel(
        self,
        call_id: str,
        result: str,
        duration_ms: int,
        error: Optional[str] = None,
    ) -> None:
        panel = self._active_tool_panels.pop(call_id, None)
        if panel is not None:
            panel.set_result(result, duration_ms, error=error)
            self._maybe_scroll_to_bottom()

    # ── Helpers ──────────────────────────────────────────────────────────

    def _lock_active_assistant(self) -> None:
        if self._active_assistant is not None:
            self.end_assistant()

    def _maybe_scroll_to_bottom(self) -> None:
        """Autoscroll only if the user is already near the bottom."""
        try:
            if self.scroll_y >= self.max_scroll_y - 3:
                self.scroll_end(animate=False)
        except Exception:
            pass
