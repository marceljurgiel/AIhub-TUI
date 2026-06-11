"""InfoBar — top info strip showing model · ctx · temp · memory · tools status.

Uses purple accent for active/online indicators. All key session info visible at
a glance without opening any modal.
"""
from __future__ import annotations

from datetime import datetime

import psutil
from textual.widgets import Static


def _k(n: int) -> str:
    """Humanize a token count: 950 → '950', 1500 → '1.5k', 32000 → '32k'."""
    n = int(n or 0)
    if n < 1000:
        return str(n)
    v = n / 1000.0
    return f"{v:.0f}k" if v >= 10 or v == int(v) else f"{v:.1f}k"


def _usage_colour(pct: float) -> str:
    """Green / amber / red by a 0–100 usage percentage."""
    if pct < 0:
        return "#6b6b73"
    if pct < 60:
        return "#22c55e"
    if pct < 85:
        return "#ffb454"
    return "#ff6e6e"


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
        # token usage
        self.ctx_used = 0
        self.ctx_max = 0
        self.session_tokens = 0
        # device usage
        self.gpu_util = -1.0          # -1 = unknown/no GPU
        self.vram_used_gb = 0.0
        self.vram_total_gb = 0.0
        self.cpu_percent = 0.0

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

        # Device usage — GPU util + VRAM when a GPU is present, else CPU + RAM.
        if self.vram_total_gb > 0:
            util = (f"[{_usage_colour(self.gpu_util)}]{self.gpu_util:.0f}%[/]"
                    if self.gpu_util >= 0 else "[#6b6b73]–[/#6b6b73]")
            vcol = _usage_colour(self.vram_used_gb / self.vram_total_gb * 100
                                 if self.vram_total_gb else 0)
            ram_str = (f"[#a8a8b0]GPU[/#a8a8b0] {util} "
                       f"[{vcol}]{self.vram_used_gb:.1f}/{self.vram_total_gb:.0f}G[/]")
        else:
            try:
                ram = psutil.virtual_memory()
                ram_g = f"[#6b6b73]RAM {ram.available / 1024**3:.1f}G[/#6b6b73]"
            except Exception:
                ram_g = "[#6b6b73]RAM ?[/#6b6b73]"
            cpu = (f"[{_usage_colour(self.cpu_percent)}]{self.cpu_percent:.0f}%[/]"
                   if self.cpu_percent else "[#6b6b73]–[/#6b6b73]")
            ram_str = f"[#a8a8b0]CPU[/#a8a8b0] {cpu}  {ram_g}"

        # Token usage — context fill + cumulative session tokens.
        if self.ctx_max:
            ratio = self.ctx_used / self.ctx_max if self.ctx_max else 0
            tcol = _usage_colour(ratio * 100)
            tok_str = (f"[#a8a8b0]ctx[/#a8a8b0] [{tcol}]{_k(self.ctx_used)}/"
                       f"{_k(self.ctx_max)}[/]")
        else:
            tok_str = "[#a8a8b0]ctx[/#a8a8b0] [#6b6b73]–[/#6b6b73]"
        if self.session_tokens:
            tok_str += f" [#6b6b73]· {_k(self.session_tokens)} tok[/#6b6b73]"

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
            f" {dot} {sep} {model_str} {sep} {tok_str} {sep}"
            f" {temp_str} {sep} {mem_str} {sep} {tools_str} {sep}"
            f" {ram_str} {sep} {clock}{agent_seg}{stream_marker}{lc_seg}"
        )
