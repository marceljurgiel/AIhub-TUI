"""GGUFPickerModal — pick a GGUF quantisation, download it, show launch command.

Flow:
  1. List available .gguf files (recommended first, ★ marker, sizes)
  2. User picks one → Download button starts streaming download to
     config.models_download_dir
  3. On success: shows the `llama-server --model …` command to run
  4. Dismisses with (model_stem, dest_path) so the picker can set backend=llamacpp
"""
from __future__ import annotations

import os
from typing import Any, Dict, List, Optional, Tuple

from textual import work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, OptionList, ProgressBar, Static
from textual.widgets.option_list import Option

from ...config import config


class GGUFPickerModal(ModalScreen[Optional[Tuple[str, str]]]):
    """Returns (model_stem, dest_path) after download, or None on cancel."""

    BINDINGS = [Binding("escape", "cancel", "Close", show=False)]

    def __init__(self, model_entry: Dict[str, Any]) -> None:
        super().__init__()
        self.model_entry = model_entry
        self.model_id = model_entry.get("name", "")
        self.gguf_files: List[Dict] = model_entry.get("gguf_files") or []
        self._downloading = False
        self._dest_path = ""
        self._model_stem = ""

    def compose(self) -> ComposeResult:
        with Container(id="gguf-container"):
            yield Static(
                f"[b][#a855f7]{self.model_id}[/#a855f7][/b]",
                id="gguf-title",
            )
            yield Static(
                "[#6b6b73]Pick a quantisation · Enter/Download · Esc close[/#6b6b73]",
                id="gguf-hint",
            )
            with VerticalScroll(id="gguf-scroll"):
                yield OptionList(*self._build_options(), id="gguf-list")
            yield ProgressBar(id="gguf-bar", total=100, show_eta=False)
            yield Static("", id="gguf-status")
            with Horizontal(id="gguf-buttons"):
                yield Button("Download", id="gguf-download", variant="success")
                yield Button("Cancel", id="gguf-cancel")

    def on_mount(self) -> None:
        # Hide progress bar until a download starts
        try:
            self.query_one("#gguf-bar", ProgressBar).display = False
        except Exception:
            pass
        # Fetch lazily when we have no files — or when the list came from a
        # search response without sizes (all 0 → would render "? GB").
        if not self.gguf_files or not any(
                f.get("size_gb") for f in self.gguf_files):
            self.query_one("#gguf-status", Static).update("[#6b6b73]Fetching file list…[/#6b6b73]")
            self._fetch_files_worker()

    def _build_options(self) -> list:
        opts = []
        for f in self.gguf_files:
            quant = f.get("quant", "?").upper()
            size = f.get("size_gb", 0)
            size_str = f"{size:.1f} GB" if size else "? GB"
            if f.get("recommended"):
                marker = "[#22c55e]★[/#22c55e]"
                tag = "  [#22c55e]recommended[/#22c55e]"
            elif f.get("quality"):
                marker = "[#a855f7]◆[/#a855f7]"
                tag = "  [#a855f7]higher quality[/#a855f7]"
            else:
                marker = " "
                tag = ""
            row = f"{marker} [#e6e6e6]{quant:<10}[/#e6e6e6]  [#a8a8b0]{size_str:<10}[/#a8a8b0]{tag}"
            opts.append(Option(row, id=f.get("filename", "")))
        if not opts:
            opts.append(Option("(no GGUF files found)", id="__none__", disabled=True))
        return opts

    # ── Lazy file fetch ──────────────────────────────────────────────────

    @work(thread=True, exclusive=True, group="gguf-files")
    def _fetch_files_worker(self) -> None:
        from ...live_registry import fetch_hf_gguf_files
        files = fetch_hf_gguf_files(self.model_id, token=config.hf_api_token)
        self.app.call_from_thread(self._populate_files, files)

    def _populate_files(self, files: List[Dict]) -> None:
        self.gguf_files = files
        try:
            olist = self.query_one("#gguf-list", OptionList)
            olist.clear_options()
            olist.add_options(self._build_options())
            status = (f"[#22c55e]{len(files)} files[/#22c55e]" if files
                      else "[#ff6e6e]No GGUF files found[/#ff6e6e]")
            self.query_one("#gguf-status", Static).update(status)
        except Exception:
            pass

    # ── Selection & download ─────────────────────────────────────────────

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        if event.option_id and event.option_id != "__none__":
            self._start_download(event.option_id)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "gguf-cancel":
            if self._downloading:
                try:
                    self.workers.cancel_group(self, "gguf-download")
                except Exception:
                    pass
            self.dismiss(None)
        elif event.button.id == "gguf-download":
            fname = self._highlighted_filename()
            if fname:
                self._start_download(fname)

    def _highlighted_filename(self) -> Optional[str]:
        try:
            olist = self.query_one("#gguf-list", OptionList)
            idx = olist.highlighted
            opt = olist.get_option_at_index(idx) if idx is not None else None
            return opt.id if opt and opt.id != "__none__" else None
        except Exception:
            return None

    def _start_download(self, filename: str) -> None:
        if self._downloading:
            return
        file_entry = next((f for f in self.gguf_files if f.get("filename") == filename), None)
        if not file_entry:
            return
        url = file_entry.get("download_url") or \
            f"https://huggingface.co/{self.model_id}/resolve/main/{filename}"
        os.makedirs(config.models_download_dir, exist_ok=True)
        dest = os.path.join(config.models_download_dir, filename)
        self._dest_path = dest
        self._model_stem = os.path.splitext(filename)[0]
        self._downloading = True
        try:
            self.query_one("#gguf-bar", ProgressBar).display = True
        except Exception:
            pass
        self.query_one("#gguf-status", Static).update(
            f"[#a855f7]Downloading {filename}…[/#a855f7]"
        )
        self._download_worker(url, dest, filename)

    @work(thread=True, exclusive=False, group="gguf-download")
    def _download_worker(self, url: str, dest: str, filename: str) -> None:
        import requests
        headers = {}
        if config.hf_api_token:
            headers["Authorization"] = f"Bearer {config.hf_api_token}"
        try:
            resp = requests.get(url, stream=True, timeout=600, headers=headers)
            resp.raise_for_status()
            total = int(resp.headers.get("content-length", 0))
            done = 0
            with open(dest, "wb") as fh:
                for chunk in resp.iter_content(chunk_size=1024 * 256):
                    if chunk:
                        fh.write(chunk)
                        done += len(chunk)
                        if total:
                            pct = min(100, int(done / total * 100))
                            self.app.call_from_thread(
                                self._set_progress, pct,
                                f"{done // 1024**2} / {total // 1024**2} MB",
                            )
            self.app.call_from_thread(self._download_done)
        except Exception as exc:
            self.app.call_from_thread(self._download_failed, str(exc))

    def _set_progress(self, pct: int, label: str) -> None:
        try:
            self.query_one("#gguf-bar", ProgressBar).progress = pct
        except Exception:
            pass
        try:
            self.query_one("#gguf-status", Static).update(
                f"[#a855f7]{label}[/#a855f7]"
            )
        except Exception:
            pass

    def _download_done(self) -> None:
        self._downloading = False
        cmd = f"llama-server --model {self._dest_path} --port 8080"
        try:
            self.query_one("#gguf-bar", ProgressBar).progress = 100
        except Exception:
            pass
        self.query_one("#gguf-status", Static).update(
            f"[#22c55e]✓ Downloaded![/#22c55e]\n\n"
            f"[#a8a8b0]Run llama.cpp with:[/#a8a8b0]\n"
            f"[#a855f7]{cmd}[/#a855f7]\n\n"
            f"[#6b6b73]Then set the URL in Settings (Ctrl+,) and select this model.[/#6b6b73]"
        )
        # Change the download button to "Done"
        try:
            btn = self.query_one("#gguf-download", Button)
            btn.label = "Done"
        except Exception:
            pass

    def _download_failed(self, err: str) -> None:
        self._downloading = False
        self.query_one("#gguf-status", Static).update(
            f"[#ff6e6e]Download failed: {err}[/#ff6e6e]"
        )

    def action_cancel(self) -> None:
        if self._downloading:
            try:
                self.workers.cancel_group(self, "gguf-download")
            except Exception:
                pass
        # If a successful download completed, return its info
        if self._dest_path and os.path.exists(self._dest_path) and not self._downloading:
            self.dismiss((self._model_stem, self._dest_path))
        else:
            self.dismiss(None)
