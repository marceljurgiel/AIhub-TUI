"""InfoBar — top info strip showing model · ctx · temp · memory · tools status.

Uses purple accent for active/online indicators. All key session info visible at
a glance without opening any modal.
"""
from __future__ import annotations

from datetime import datetime

import psutil
from textual.widgets import Static


class StatusBar(Static):
    DEFAULT_CSS = ""

    def __init__(self) -> None:
        super().__init__("loading…")
        self.ollama_online = False
        self.llamacpp_online = False
        self.llamacpp_model = ""
        self.model_name = "(no model)"
        self.context_length = 2048
        self.context_used = 0
        self.temperature = 0.7
        self.memory_enabled = False
        self.tools_enabled = True
        self.streaming = False
        self.agent_mode = False
        self.agent_submode = "build"

    def on_mount(self) -> None:
        self.refresh_status()
        self.set_interval(15.0, self.refresh_status)

    def refresh_status(self) -> None:
        # Ollama dot — green when online
        if self.ollama_online:
            dot = "[#22c55e]●[/#22c55e]"
        else:
            dot = "[#ff6e6e]○[/#ff6e6e]"

        # Model name (purple)
        if self.model_name and self.model_name != "(no model)":
            model_str = f"[b][#a855f7]{self.model_name}[/#a855f7][/b]"
        else:
            model_str = "[#6b6b73]no model[/#6b6b73]"

        # Context (purple — informational)
        ctx_str = (
            f"[#a855f7]{self.context_length // 1024}k[/#a855f7]"
            if self.context_length >= 1024
            else f"[#a855f7]{self.context_length}[/#a855f7]"
        )

        # Temperature (purple — informational)
        temp_str = f"[#a855f7]T {self.temperature:.1f}[/#a855f7]"

        # Memory — green when ON, grey when off
        if self.memory_enabled:
            mem_str = "[#22c55e]mem ✓[/#22c55e]"
        else:
            mem_str = "[#6b6b73]mem ·[/#6b6b73]"

        # Tools — green when ON, grey when off
        if self.tools_enabled:
            tools_str = "[#22c55e]tools ✓[/#22c55e]"
        else:
            tools_str = "[#6b6b73]tools ·[/#6b6b73]"

        # RAM
        try:
            ram = psutil.virtual_memory()
            ram_str = f"[#6b6b73]RAM {ram.available / 1024**3:.1f}G[/#6b6b73]"
        except Exception:
            ram_str = "[#6b6b73]RAM ?[/#6b6b73]"

        # Agent mode indicator
        agent_seg = ""
        if self.agent_mode:
            agent_seg = f"  [b][#a855f7]◆ agent · {self.agent_submode}[/#a855f7][/b]"

        # Streaming indicator
        stream_marker = "  [#ffb454]⟳ streaming…[/#ffb454]" if self.streaming else ""

        # Clock
        clock = f"[#6b6b73]{datetime.now().strftime('%H:%M')}[/#6b6b73]"

        # llama.cpp indicator (shown only when enabled)
        from ...config import config as _cfg
        lc_seg = ""
        if _cfg.llamacpp_enabled:
            if self.llamacpp_online:
                lc_model = f" [#a855f7]{self.llamacpp_model}[/#a855f7]" if self.llamacpp_model else ""
                lc_seg = f"  [#a8a8b0]llama.cpp[/#a8a8b0] [#22c55e]●[/#22c55e]{lc_model}"
            else:
                lc_seg = "  [#a8a8b0]llama.cpp[/#a8a8b0] [#6b6b73]○[/#6b6b73]"

        sep = "[#2a2a30] │ [/#2a2a30]"
        self.update(
            f" {dot} {sep} {model_str} {sep} ctx {ctx_str} {sep}"
            f" {temp_str} {sep} {mem_str} {sep} {tools_str} {sep}"
            f" {ram_str} {sep} {clock}{agent_seg}{stream_marker}{lc_seg}"
        )
