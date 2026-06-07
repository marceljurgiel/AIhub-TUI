"""OllamaVariantModal — pick a size/quant variant of an Ollama library model.

A model like `gemma3` ships many tags (1b, 4b, 12b, 27b, plus quant variants).
This modal parses those tags, estimates each variant's download size and RAM
need, flags which fit the user's available RAM (green = fits, grey = too big),
and returns the chosen `name:tag` so the picker can `ollama pull` it.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, OptionList, Static
from textual.widgets.option_list import Option

from ...hardware import get_available_ram_gb


# GB of file size per billion parameters, by quantisation family.
_GB_PER_B = {
    "q2":   0.42, "q3": 0.50, "q4": 0.65, "q5": 0.75,
    "q6":   0.85, "q8": 1.10, "fp16": 2.0, "f16": 2.0, "qat": 0.65,
}
_DEFAULT_GB_PER_B = 0.65   # bare tags default to ~q4_K_M

_PARAM_RE = re.compile(r"(\d+(?:\.\d+)?)\s*b\b", re.IGNORECASE)
_QUANT_RE = re.compile(r"(q\d+|fp16|f16|qat)", re.IGNORECASE)


def _estimate_variant(tag: str) -> Tuple[float, float]:
    """Return (download_gb, ram_need_gb) estimated from a tag string.
    Returns (0, 0) when no parameter count is found."""
    pm = _PARAM_RE.search(tag)
    if not pm:
        return 0.0, 0.0
    params_b = float(pm.group(1))
    qm = _QUANT_RE.search(tag)
    if qm:
        key = qm.group(1).lower()
        family = key[:2] if key.startswith("q") else key
        gb_per_b = _GB_PER_B.get(family, _DEFAULT_GB_PER_B)
    else:
        gb_per_b = _DEFAULT_GB_PER_B
    download_gb = params_b * gb_per_b
    ram_need = download_gb * 1.2 + 0.5     # weights + KV cache + overhead
    return round(download_gb, 1), round(ram_need, 1)


class OllamaVariantModal(ModalScreen[Optional[str]]):
    """Returns the chosen tag like 'gemma3:4b', or None on cancel."""

    BINDINGS = [Binding("escape", "cancel", "Close", show=False)]

    def __init__(self, model_entry: Dict[str, Any]) -> None:
        super().__init__()
        self.model_name = model_entry.get("name", "")
        self.tags: List[str] = model_entry.get("tags") or []
        self.description = model_entry.get("description", "")
        self.hw_ram = 0.0

    def compose(self) -> ComposeResult:
        with Container(id="ov-container"):
            yield Static(f"[b][#a855f7]{self.model_name}[/#a855f7][/b]", id="ov-title")
            yield Static(f"[#6b6b73]{self.description}[/#6b6b73]", id="ov-desc")
            yield Static("", id="ov-hw")
            with VerticalScroll(id="ov-scroll"):
                yield OptionList(id="ov-list")
            with Horizontal(id="ov-buttons"):
                yield Button("Download & use", id="ov-use", variant="success")
                yield Button("Cancel", id="ov-cancel")

    def on_mount(self) -> None:
        try:
            self.hw_ram = get_available_ram_gb()
        except Exception:
            self.hw_ram = 0.0
        self.query_one("#ov-hw", Static).update(
            f"[#a8a8b0]Your available RAM: [#a855f7]{self.hw_ram:.1f} GB[/#a855f7]"
            "  ·  [#22c55e]green[/#22c55e] fits · [#6b6b73]grey[/#6b6b73] too big[/#a8a8b0]"
        )
        self._populate()

    def _populate(self) -> None:
        # Build a row per tag, estimate size, sort by size ascending.
        rows: List[Tuple[float, str, str]] = []   # (sort_key, tag, rendered)
        for tag in self.tags:
            dl_gb, ram_need = _estimate_variant(tag)
            full = f"{self.model_name}:{tag}"
            if dl_gb <= 0:
                # Unknown size (e.g. "latest")
                rows.append((9999.0, tag,
                    f"  [#a8a8b0]{tag:<22}[/#a8a8b0]  [#6b6b73]size unknown[/#6b6b73]"))
                continue
            fits = (self.hw_ram <= 0) or (ram_need <= self.hw_ram)
            if fits:
                marker = "[#22c55e]✓[/#22c55e]"
                colour = "#e6e6e6"
                fit_txt = "[#22c55e]fits[/#22c55e]"
            else:
                marker = "[#6b6b73]✘[/#6b6b73]"
                colour = "#6b6b73"
                fit_txt = "[#6b6b73]too big[/#6b6b73]"
            row = (
                f"{marker} [{colour}]{tag:<22}[/{colour}]  "
                f"[#a8a8b0]{dl_gb:>5.1f} GB dl[/#a8a8b0]  "
                f"[#6b6b73]~{ram_need:.1f} GB RAM[/#6b6b73]  {fit_txt}"
            )
            rows.append((dl_gb, tag, row))

        rows.sort(key=lambda r: r[0])
        opts = [Option(rendered, id=tag) for _key, tag, rendered in rows]
        if not opts:
            opts = [Option("(no variants found)", id="__none__", disabled=True)]
        olist = self.query_one("#ov-list", OptionList)
        olist.clear_options()
        olist.add_options(opts)

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        self._choose(event.option_id)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "ov-cancel":
            self.dismiss(None)
        elif event.button.id == "ov-use":
            self._choose(self._highlighted())

    def _highlighted(self) -> Optional[str]:
        try:
            olist = self.query_one("#ov-list", OptionList)
            idx = olist.highlighted
            opt = olist.get_option_at_index(idx) if idx is not None else None
            return opt.id if opt and opt.id != "__none__" else None
        except Exception:
            return None

    def _choose(self, tag: Optional[str]) -> None:
        if not tag or tag == "__none__":
            return
        self.dismiss(f"{self.model_name}:{tag}")

    def action_cancel(self) -> None:
        self.dismiss(None)
