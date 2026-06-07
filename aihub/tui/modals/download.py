"""DownloadModal — live progress bar for `ollama pull`."""
from __future__ import annotations

from textual import work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container
from textual.screen import ModalScreen
from textual.widgets import ProgressBar, Static


class DownloadModal(ModalScreen[bool]):
    """Push this modal to pull a model. Returns True on success, False on cancel/error."""

    BINDINGS = [Binding("escape", "cancel_dl", "Cancel", show=False)]

    def __init__(self, model_name: str) -> None:
        super().__init__()
        self.model_name = model_name

    def compose(self) -> ComposeResult:
        with Container(id="dl-container"):
            yield Static(
                f"[b]Downloading[/b] [#a855f7]{self.model_name}[/#a855f7]",
                id="dl-title",
            )
            yield ProgressBar(id="dl-bar", total=100, show_eta=False)
            yield Static("Connecting…", id="dl-status")
            yield Static("[#6b6b73]Esc to cancel[/#6b6b73]", id="dl-hint")

    def on_mount(self) -> None:
        self._pull()

    @work(thread=True, exclusive=False, group="download")
    def _pull(self) -> None:
        from ...ollama_client import pull_model_stream

        def _update(pct: int, status: str) -> None:
            try:
                self.app.call_from_thread(self._set_progress, pct, status)
            except Exception:
                pass

        try:
            last_status = ""
            for chunk in pull_model_stream(self.model_name):
                if "error" in chunk:
                    _update(0, f"Error: {chunk['error']}")
                    self.app.call_from_thread(self.dismiss, False)
                    return
                status = chunk.get("status", "")
                completed = chunk.get("completed", 0)
                total = chunk.get("total", 0)
                if total:
                    pct = min(100, int(completed / total * 100))
                    _update(pct, status)
                elif status and status != last_status:
                    _update(0, status)
                last_status = status
            self.app.call_from_thread(self._set_progress, 100, "Complete!")
            self.app.call_from_thread(self.dismiss, True)
        except Exception as exc:
            self.app.call_from_thread(self._set_progress, 0, f"Failed: {exc}")
            self.app.call_from_thread(self.dismiss, False)

    def _set_progress(self, pct: int, status: str) -> None:
        try:
            bar = self.query_one("#dl-bar", ProgressBar)
            bar.progress = pct
        except Exception:
            pass
        try:
            self.query_one("#dl-status", Static).update(status)
        except Exception:
            pass

    def action_cancel_dl(self) -> None:
        self.workers.cancel_group(self, "download")
        self.dismiss(False)
