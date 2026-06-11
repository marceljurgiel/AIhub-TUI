"""
AIHub TUI — session state container.

Holds per-session reactive data. Owned by ChatScreen; passed by reference to
worker code that needs read-only access to messages, etc.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional


@dataclass
class SessionState:
    model_name: Optional[str] = None
    messages: List[Dict[str, Any]] = field(default_factory=list)
    temperature: float = 0.7
    context_length: int = 2048
    memory_enabled: bool = False
    tools_enabled: bool = True
    backend: str = "ollama"          # "ollama" | "llamacpp" | "api"
    stream_model: str = ""           # actual id passed to the stream (e.g. api:// url)
    mode: str = "chat"               # "chat" | "agent"
    agent_submode: str = "build"     # "plan" | "build" (when mode == "agent")
    session_tokens: int = 0          # cumulative tokens used this session
    ctx_used: int = 0                # prompt tokens of the latest model call
    start_time: datetime = field(default_factory=datetime.now)

    def reset_for(self, model_name: str, context_length: int) -> None:
        self.model_name = model_name
        self.context_length = context_length
        self.messages = []
        self.memory_enabled = False
        self.backend = "ollama"
        self.stream_model = ""
        self.mode = "chat"
        self.agent_submode = "build"
        self.session_tokens = 0
        self.ctx_used = 0
        self.start_time = datetime.now()
