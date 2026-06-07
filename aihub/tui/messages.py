"""
AIHub TUI — cross-widget message types.

Centralised so the contract between widgets / screens / workers is documented
in one place. Workers post these from background threads; screens handle on
the UI thread.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from textual.message import Message

from ..chat import ChatEvent
from ..slash import SlashResult


class ChatEventReceived(Message):
    """Wraps a single ChatEvent emitted by the chat stream worker."""
    def __init__(self, event: ChatEvent) -> None:
        super().__init__()
        self.event = event


class InputSubmitted(Message):
    """The user pressed Enter on a non-empty input."""
    def __init__(self, text: str) -> None:
        super().__init__()
        self.text = text


class OllamaStatusChanged(Message):
    """Periodic poll result; published from the backends-poll worker."""
    def __init__(self, online: bool) -> None:
        super().__init__()
        self.online = online


class LlamaCppStatusChanged(Message):
    """Periodic poll result for llama.cpp backend."""
    def __init__(self, online: bool, model_name: str = "") -> None:
        super().__init__()
        self.online = online
        self.model_name = model_name


class ModelChangeRequested(Message):
    """ModelPicker selected a model."""
    def __init__(self, model_name: str, context_length: int) -> None:
        super().__init__()
        self.model_name = model_name
        self.context_length = context_length


class SessionLoadRequested(Message):
    """HistoryModal selected a session to resume."""
    def __init__(self, model_name: str, messages: List[Dict[str, Any]]) -> None:
        super().__init__()
        self.model_name = model_name
        self.messages = messages


class StreamCancelRequested(Message):
    """User pressed Esc while streaming."""


class SlashCommandParsed(Message):
    """ChatInput intercepted a slash command; ChatScreen dispatches it."""
    def __init__(self, result: SlashResult) -> None:
        super().__init__()
        self.result = result


class SlashQuery(Message):
    """ChatInput text changed and starts with '/'; update the autocomplete popup."""
    def __init__(self, text: str) -> None:
        super().__init__()
        self.text = text


class SlashNavigate(Message):
    """User pressed Up/Down/Tab/Enter while the slash popup is visible."""
    def __init__(self, key: str) -> None:
        super().__init__()
        self.key = key


class MemoryUpdated(Message):
    """Memory modal or memoryadd extractor signalled a write."""
    def __init__(self, model_name: str, summary: Optional[str] = None) -> None:
        super().__init__()
        self.model_name = model_name
        self.summary = summary
