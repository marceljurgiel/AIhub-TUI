"""Collapsible inline tool-call panel for the chat log.

State transitions:
  running     ⟳ name(arg-preview)            (orange border)
  complete    ▸ name(arg-preview)  [Xms]     (default border, expandable)
  errored     ✗ name(arg-preview)  [Xms]     (red border, expandable)
"""
from __future__ import annotations

import json
from typing import Any, Dict, Optional

from textual.app import ComposeResult
from textual.widgets import Collapsible, Static


def _arg_preview(args: Dict[str, Any], width: int = 60) -> str:
    try:
        text = json.dumps(args, ensure_ascii=False)
    except Exception:
        text = str(args)
    return text if len(text) <= width else text[: width - 1] + "…"


class ToolCallPanel(Collapsible):
    """One tool round. Collapsed by default; Enter expands."""

    def __init__(
        self,
        call_id: str,
        name: str,
        arguments: Dict[str, Any],
    ) -> None:
        self.call_id = call_id
        self.tool_name = name
        self.arguments = arguments
        super().__init__(
            title=self._render_title("running"),
            collapsed=True,
            classes="running",
        )
        self._args_widget: Optional[Static] = None
        self._result_widget: Optional[Static] = None
        self._duration_ms: Optional[int] = None
        self._error: Optional[str] = None

    def compose(self) -> ComposeResult:
        args_text = json.dumps(self.arguments, ensure_ascii=False, indent=2)
        self._args_widget = Static(f"args: {args_text}", markup=False)
        self._result_widget = Static("(running…)", markup=False)
        yield self._args_widget
        yield self._result_widget

    def _render_title(self, status: str) -> str:
        preview = _arg_preview(self.arguments)
        if status == "running":
            return f"⟳ {self.tool_name}({preview})"
        if status == "errored":
            return f"✗ {self.tool_name}({preview})  [{self._duration_ms}ms]"
        return f"▸ {self.tool_name}({preview})  [{self._duration_ms}ms]"

    def set_result(
        self,
        result: str,
        duration_ms: int,
        error: Optional[str] = None,
    ) -> None:
        self._duration_ms = duration_ms
        self._error = error
        status = "errored" if error else "complete"
        self.title = self._render_title(status)
        self.set_class(status == "errored", "errored")
        self.set_class(False, "running")
        if self._result_widget is not None:
            truncated = result if len(result) <= 4000 else (
                result[:4000] + f"\n…(truncated, {len(result)} bytes total)"
            )
            self._result_widget.update(truncated)
