"""HardwareModal — rich system diagnostics with colour-coded bars."""
from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Static

from ...hardware import (
    get_cpu_info, get_disk_info, get_gpu_info, get_os_info, get_ram_info,
)


def _bar(used: float, total: float, width: int = 20) -> str:
    """Render a coloured usage bar  ████░░░░  with colour based on % used."""
    if total <= 0:
        return "[#6b6b73]" + "─" * width + "[/#6b6b73]"
    pct = min(1.0, used / total)
    filled = round(pct * width)
    empty = width - filled
    if pct < 0.6:
        colour = "#22c55e"   # green — plenty free
    elif pct < 0.85:
        colour = "#ffb454"   # amber — getting tight
    else:
        colour = "#ff6e6e"   # red — nearly full
    bar = f"[{colour}]{'█' * filled}[/{colour}][#2a2a30]{'░' * empty}[/#2a2a30]"
    return bar


def _pct_colour(pct: float) -> str:
    if pct < 60:
        return "#22c55e"
    if pct < 85:
        return "#ffb454"
    return "#ff6e6e"


def _hw_text() -> str:
    try:
        cpu  = get_cpu_info()
        ram  = get_ram_info()
        disk = get_disk_info()
        gpu  = get_gpu_info()
        os_str = get_os_info()
    except Exception as exc:
        return f"[#ff6e6e]Hardware probe failed: {exc}[/#ff6e6e]"

    # ── OS ──────────────────────────────────────────────────────────────
    # Shorten the OS string a bit
    os_short = os_str.replace("-with-glibc2.", " glibc ") if os_str else "?"

    # ── CPU ─────────────────────────────────────────────────────────────
    cpu_model  = cpu.get("model", "?")
    cpu_phys   = cpu.get("cores_physical", "?")
    cpu_logic  = cpu.get("cores_logical", "?")
    cpu_pct    = cpu.get("usage_percent", 0)
    cpu_colour = _pct_colour(cpu_pct)

    # ── RAM ─────────────────────────────────────────────────────────────
    ram_total  = ram.get("total_gb", 0)
    ram_avail  = ram.get("available_gb", 0)
    ram_used   = ram_total - ram_avail
    ram_pct    = ram.get("percent_used", 0)

    # ── Disk ────────────────────────────────────────────────────────────
    disk_total = disk.get("total_gb", 0)
    disk_free  = disk.get("free_gb", 0)
    disk_used  = disk_total - disk_free
    disk_pct   = disk.get("percent_used", 0)

    # ── GPU / VRAM ───────────────────────────────────────────────────────
    gpu_vendor = gpu.get("vendor", "?")
    gpu_model  = gpu.get("model", "?")
    vram_total_mb = gpu.get("vram_total_mb", 0)
    vram_free_mb  = gpu.get("vram_free_mb", 0)
    vram_used_mb  = vram_total_mb - vram_free_mb
    has_gpu = vram_total_mb > 0

    sep   = "[#2a2a30]─────────────────────────────────────────────[/#2a2a30]"
    label = "[#a855f7]"
    lend  = "[/#a855f7]"
    dim   = "[#6b6b73]"
    dend  = "[/#6b6b73]"

    lines = [
        f" [b][#a855f7]◆ System Diagnostics[/#a855f7][/b]   {dim}r refresh · Esc close{dend}",
        "",
        sep,
        f" {label}OS     {lend}[#e6e6e6]{os_short}[/#e6e6e6]",
        sep,
        "",
        # CPU
        f" {label}CPU    {lend}[#e6e6e6]{cpu_model}[/#e6e6e6]",
        f" {dim}       {cpu_phys} physical  ·  {cpu_logic} logical cores{dend}",
        f" {label}Usage  {lend}{_bar(cpu_pct, 100)}  [{cpu_colour}]{cpu_pct:.1f}%[/{cpu_colour}]",
        "",
        sep,
        "",
        # RAM
        f" {label}RAM    {lend}[#e6e6e6]{ram_used:.1f} / {ram_total:.1f} GB used[/#e6e6e6]   "
            f"{dim}({ram_avail:.1f} GB free){dend}",
        f"        {_bar(ram_used, ram_total)}  [{_pct_colour(ram_pct)}]{ram_pct:.1f}%[/{_pct_colour(ram_pct)}]",
        "",
        # Disk
        f" {label}Disk   {lend}[#e6e6e6]{disk_used:.1f} / {disk_total:.1f} GB used[/#e6e6e6]   "
            f"{dim}({disk_free:.1f} GB free){dend}",
        f"        {_bar(disk_used, disk_total)}  [{_pct_colour(disk_pct)}]{disk_pct:.1f}%[/{_pct_colour(disk_pct)}]",
        "",
        sep,
        "",
        # GPU
        f" {label}GPU    {lend}[#e6e6e6]{gpu_vendor} — {gpu_model}[/#e6e6e6]",
    ]

    if has_gpu:
        vram_pct = (vram_used_mb / vram_total_mb * 100) if vram_total_mb else 0
        lines += [
            f" {label}VRAM   {lend}[#e6e6e6]{vram_used_mb/1024:.1f} / {vram_total_mb/1024:.1f} GB used[/#e6e6e6]   "
                f"{dim}({vram_free_mb/1024:.1f} GB free){dend}",
            f"        {_bar(vram_used_mb, vram_total_mb)}  "
                f"[{_pct_colour(vram_pct)}]{vram_pct:.1f}%[/{_pct_colour(vram_pct)}]",
        ]
    else:
        lines.append(f" {dim}       No dedicated VRAM detected (integrated graphics){dend}")

    lines += ["", sep]
    return "\n".join(lines)


class HardwareModal(ModalScreen):
    BINDINGS = [
        Binding("escape", "close", "Close", show=False),
        Binding("q", "close", "Close", show=False),
        Binding("r", "refresh", "Refresh", show=False),
    ]

    def compose(self) -> ComposeResult:
        with Container(id="hw-container"):
            with VerticalScroll():
                yield Static(_hw_text(), id="hw-body")

    def action_refresh(self) -> None:
        try:
            self.query_one("#hw-body", Static).update(_hw_text())
            self.notify("Refreshed.", severity="information")
        except Exception:
            pass

    def action_close(self) -> None:
        self.dismiss(None)
