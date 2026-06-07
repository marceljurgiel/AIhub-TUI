"""
AIHub TUI — OpenCode-style chat-first Textual app.

Public entry point is `run()`; the typer callback in cli.py launches it.
"""
from __future__ import annotations


def run() -> None:
    """Boot the AIHub TUI app."""
    from .app import AIHubApp
    AIHubApp().run()


__all__ = ["run"]
