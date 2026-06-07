"""
AIHub — Slash-command parser.

Maps a raw `/command ...` string to a typed `SlashResult` describing intent.
This module performs no I/O and has no side effects — callers dispatch on
`SlashResult.kind` to their own renderers (CLI Rich panels in chat_cli.py;
modals + system bubbles in tui/chat_screen.py).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Optional


# Canonical command kinds. Keep this list authoritative; consumers should
# pattern-match on it.
SlashKind = str  # Literal use is awkward across py3.9/3.10; keep as str.

KIND_HELP            = "help"
KIND_TOOLS_INFO      = "tools_info"
KIND_CLEAR           = "clear"
KIND_NEW_CHAT        = "new_chat"
KIND_MEMORY_SHOW     = "memory_show"
KIND_MEMORY_SAVE     = "memory_save"
KIND_MEMORY_CLEAR    = "memory_clear"
KIND_MEMORY_EXTRACT  = "memory_extract"   # payload: {"target": "chat"|"global"}
KIND_HISTORY_BROWSE  = "history_browse"
KIND_USAGE           = "usage"            # malformed but recognised command
KIND_UNKNOWN         = "unknown"


@dataclass(frozen=True)
class SlashResult:
    kind: SlashKind
    payload: Dict[str, Any] = field(default_factory=dict)
    message: Optional[str] = None  # human-readable usage / status hint


def parse_slash(raw: str) -> SlashResult:
    """Parse a slash command.

    Recognised forms:
      /help
      /tools
      /clear
      /memory
      /memory save <key> <value...>
      /memory clear
      /memoryadd [chat|global]
      /history
    """
    if not raw.startswith("/"):
        return SlashResult(kind=KIND_UNKNOWN, message=f"Not a slash command: {raw!r}")

    parts = raw.split(maxsplit=2)
    head = parts[0].lower()

    if head == "/help":
        return SlashResult(kind=KIND_HELP)

    if head == "/tools":
        return SlashResult(kind=KIND_TOOLS_INFO)

    if head in ("/clear", "/new"):
        kind = KIND_NEW_CHAT if head == "/new" else KIND_CLEAR
        return SlashResult(kind=kind)

    if head == "/history":
        return SlashResult(kind=KIND_HISTORY_BROWSE)

    if head == "/memory":
        sub = parts[1].lower() if len(parts) > 1 else ""
        if not sub:
            return SlashResult(kind=KIND_MEMORY_SHOW)
        if sub == "clear":
            return SlashResult(kind=KIND_MEMORY_CLEAR)
        if sub == "save":
            if len(parts) < 3:
                return SlashResult(
                    kind=KIND_USAGE,
                    message="Usage: /memory save <key> <value>",
                )
            kv = parts[2].split(maxsplit=1)
            if len(kv) != 2 or not kv[0] or not kv[1].strip():
                return SlashResult(
                    kind=KIND_USAGE,
                    message="Usage: /memory save <key> <value>",
                )
            return SlashResult(
                kind=KIND_MEMORY_SAVE,
                payload={"key": kv[0], "value": kv[1].strip()},
            )
        return SlashResult(
            kind=KIND_USAGE,
            message=f"Unknown /memory subcommand: {sub!r}. Try /memory, /memory save <key> <value>, /memory clear.",
        )

    if head == "/memoryadd":
        target = parts[1].lower() if len(parts) > 1 else "chat"
        if target not in ("chat", "global"):
            return SlashResult(
                kind=KIND_USAGE,
                message="Usage: /memoryadd [chat|global]",
            )
        return SlashResult(
            kind=KIND_MEMORY_EXTRACT,
            payload={"target": target},
        )

    return SlashResult(
        kind=KIND_UNKNOWN,
        message=f"Unknown command: {head}. Type /help for the list.",
    )


# Help text shared by CLI and TUI renderers. Plain-text; consumers can wrap.
HELP_TEXT = """\
[b][#a855f7]Keyboard shortcuts:[/#a855f7][/b]
  Ctrl+O  Models      Ctrl+R  History     Ctrl+E  Memory
  Ctrl+B  Hardware    Ctrl+,  Settings    Ctrl+P  Palette
  Ctrl+L  Clear       Ctrl+N  New chat    Ctrl+S  Save
  Ctrl+T  Tools on/off        Esc  Cancel stream
  F1      Help        Ctrl+Q  Quit

[b][#a855f7]Slash commands:[/#a855f7][/b]
  /new                        Save session & start a fresh chat
  /help                       Show this help
  /model                      Switch model
  /memory                     Show current memory
  /memory save <key> <value>  Save a fact to memory
  /memory clear               Clear memory for this model
  /memoryadd chat             Auto-extract facts → model memory
  /memoryadd global           Auto-extract facts → global memory
  /history                    Browse & resume past sessions
  /tools                      List available agentic tools
  /clear                      Clear chat context (keep system)
  exit / quit / q             End the session
"""
