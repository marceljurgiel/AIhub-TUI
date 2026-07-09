"""Top header bar + bottom vim-style status line.

`StatusBar`  — docked top: session title · status · message count  |  device ·
               context fill · model pill.
`FooterBar`  — docked bottom: MODE · path · model · mem/tools/temp  |  tok/s · clock.

Both read the same flat set of attributes, pushed by ChatScreen._sync_status(),
and render a single right-padded line via render() (Textual measures Rich Tables
as zero-height, so we lay out the left/right split manually using the widget
width, which is known at render() time).
"""
from __future__ import annotations

import os
from datetime import datetime

import psutil
from rich.text import Text
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


class _BarBase(Static):
    """Shared status attributes + left/right split rendering for both bars."""

    DEFAULT_CSS = ""

    def __init__(self) -> None:
        super().__init__("")
        self.ollama_online = False
        self.llamacpp_online = False
        self.llamacpp_model = ""
        self.model_name = "(no model)"
        self.context_length = 2048
        self.temperature = 0.7
        self.memory_enabled = False
        self.tools_enabled = True
        self.streaming = False
        self.agent_mode = False
        self.agent_submode = "build"
        # session meta
        self.session_title = "new session"
        self.message_count = 0
        # token usage
        self.ctx_used = 0
        self.ctx_max = 0
        self.session_tokens = 0
        self.tps = 0.0          # generation speed (tokens/second)
        # device usage
        self.gpu_util = -1.0
        self.vram_used_gb = 0.0
        self.vram_total_gb = 0.0
        self.cpu_percent = 0.0
        # Where the loaded model actually runs (from Ollama /api/ps):
        # True = GPU (fully/partially), False = CPU, None = unknown/not loaded.
        self.model_on_gpu = None

    def on_mount(self) -> None:
        self.refresh_status()
        self.set_interval(15.0, self.refresh_status)

    def refresh_status(self) -> None:
        # render() does the work; just trigger a repaint.
        self.refresh()

    # convenience ----------------------------------------------------------
    def _model_short(self, width: int = 28) -> str:
        m = self.model_name or ""
        if not m or m == "(no model)":
            return ""
        return m if len(m) <= width else m[: width - 1] + "…"

    def _ctx_markup(self) -> str:
        if self.ctx_max:
            ratio = (self.ctx_used / self.ctx_max) if self.ctx_max else 0
            col = _usage_colour(ratio * 100)
            return f"[{col}]{_k(self.ctx_used)}/{_k(self.ctx_max)}[/{col}]"
        if self.context_length:
            return f"[#6b6b73]0/{_k(self.context_length)}[/#6b6b73]"
        return "[#6b6b73]–[/#6b6b73]"

    def _tps_markup(self) -> str:
        """Generation speed, colour-coded: fast→green, medium→amber, slow→red
        (slow usually means CPU)."""
        if not self.tps or self.tps <= 0:
            return ""
        col = "#22c55e" if self.tps >= 20 else ("#ffb454" if self.tps >= 8 else "#ff6e6e")
        return f"[{col}]{self.tps:.0f} tok/s[/{col}]"

    def _device_markup(self) -> str:
        # Show the device actually doing the work: if the loaded model is
        # confirmed to run on CPU, show the CPU counter even when a GPU exists.
        if self.vram_total_gb > 0 and self.model_on_gpu is not False:
            util = (f"[{_usage_colour(self.gpu_util)}]{self.gpu_util:.0f}%[/]"
                    if self.gpu_util >= 0 else "[#6b6b73]–[/#6b6b73]")
            vcol = _usage_colour(self.vram_used_gb / self.vram_total_gb * 100)
            return (f"[#6b6b73]GPU[/#6b6b73] {util} "
                    f"[{vcol}]{self.vram_used_gb:.1f}/{self.vram_total_gb:.0f}G[/]")
        cpu = (f"[{_usage_colour(self.cpu_percent)}]{self.cpu_percent:.0f}%[/]"
               if self.cpu_percent else "[#6b6b73]–[/#6b6b73]")
        try:
            free = psutil.virtual_memory().available / 1024**3
            ram = f"[#6b6b73]{free:.1f}G[/#6b6b73]"
        except Exception:
            ram = ""
        return f"[#6b6b73]CPU[/#6b6b73] {cpu} {ram}"

    def _split(self, left_markup: str, right_markup: str) -> Text:
        """One line: left-justified + right-justified, padded to the widget
        width. Left side is ellipsis-truncated if the two would overlap."""
        left = Text.from_markup(left_markup)
        right = Text.from_markup(right_markup)
        width = max(int(self.size.width) or 0, 1)
        if left.cell_len + right.cell_len + 1 > width:
            left.truncate(max(0, width - right.cell_len - 1), overflow="ellipsis")
        pad = max(1, width - left.cell_len - right.cell_len)
        out = Text()
        out.append_text(left)
        out.append(" " * pad)
        out.append_text(right)
        return out


class StatusBar(_BarBase):
    """Top header — title · status · messages  |  device · ctx · model."""

    def render(self) -> Text:
        title = self.session_title or "new session"
        if self.streaming:
            status = "[#ffb454]streaming…[/#ffb454]"
        elif self.agent_mode:
            status = f"[#a855f7]agent · {self.agent_submode}[/#a855f7]"
        else:
            status = "[#6b6b73]active session[/#6b6b73]"
        dot = "[#a855f7]●[/#a855f7]"
        sep = "[#2a2a30]·[/#2a2a30]"
        left = (f"{dot} [b]{title}[/b]  {sep} {status}  {sep} "
                f"[#6b6b73]{self.message_count} messages[/#6b6b73]")

        odot = "[#22c55e]●[/#22c55e]" if self.ollama_online else "[#6b6b73]○[/#6b6b73]"
        model = self._model_short()
        pill = (f"{odot} [#a855f7]{model}[/#a855f7] [#6b6b73]▾[/#6b6b73]"
                if model else f"{odot} [#6b6b73]no model ▾[/#6b6b73]")
        tps = self._tps_markup()
        tps_seg = f"{tps}  {sep} " if tps else ""
        right = (f"{tps_seg}[#a8a8b0]ctx[/#a8a8b0] {self._ctx_markup()}  {sep} "
                 f"{self._device_markup()}  {sep} {pill}")
        return self._split(left, right)


class FooterBar(_BarBase):
    """Bottom vim-style line — MODE · path · model · flags  |  tok/s · clock."""

    def render(self) -> Text:
        if self.agent_mode:
            mode = f"AGENT·{self.agent_submode.upper()}"
            modecol = "#ffb454"
        elif self.streaming:
            mode, modecol = "STREAM", "#a855f7"
        else:
            mode, modecol = "NORMAL", "#a855f7"
        mode_block = f"[on {modecol}][#0e0e10] {mode} [/#0e0e10][/]"

        try:
            from ...config import config as _cfg
            base = os.path.basename(_cfg.project_dir.rstrip("/")) if _cfg.project_dir else ""
        except Exception:
            base = ""
        path = f"[#6b6b73]~/{base or 'aihub'}[/#6b6b73]"

        model = self._model_short(24)
        mdot = "[#22c55e]●[/#22c55e]" if model else "[#6b6b73]●[/#6b6b73]"
        model_seg = (f"{mdot} [#a8a8b0]{model}[/#a8a8b0]" if model
                     else f"{mdot} [#6b6b73]no model[/#6b6b73]")

        mem = "[#22c55e]mem ✓[/#22c55e]" if self.memory_enabled else "[#6b6b73]mem ·[/#6b6b73]"
        tools = "[#22c55e]tools ✓[/#22c55e]" if self.tools_enabled else "[#6b6b73]tools ·[/#6b6b73]"
        temp = f"[#6b6b73]T {self.temperature:.1f}[/#6b6b73]"
        sep = "[#2a2a30]·[/#2a2a30]"
        left = f"{mode_block} {path}  {sep} {model_seg}  {sep} {mem}  {tools}  {temp}"

        # No ctx counter here — the top StatusBar already shows it.
        clock = f"[#6b6b73]{datetime.now().strftime('%H:%M')}[/#6b6b73]"
        tps = self._tps_markup()
        tps_seg = f"{tps}  {sep} " if tps else ""
        right = f"{tps_seg}{clock}"
        return self._split(left, right)
