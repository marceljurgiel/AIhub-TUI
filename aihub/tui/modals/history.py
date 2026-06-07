"""HistoryModal — pick a saved session to resume."""
from __future__ import annotations

import os
from typing import Any, Dict, List, Optional, Tuple

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal
from textual.screen import ModalScreen
from textual.widgets import Button, OptionList, Static
from textual.widgets.option_list import Option

from ...api_models import resolve_api_url
from ...config import HISTORY_DIR
from ...history import delete_session, list_sessions, load_session_full


class HistoryModal(
    ModalScreen[Optional[Tuple[str, List[Dict[str, Any]], str, str]]]
):
    """Returns (model_name, messages, backend, stream_model) on resume,
    or None on cancel."""

    BINDINGS = [
        Binding("escape", "cancel", "Close", show=False),
        Binding("d", "delete", "Delete", show=False),
        Binding("r", "refresh", "Refresh", show=False),
    ]

    def compose(self) -> ComposeResult:
        with Container():
            yield Static(
                "[b]History[/b]   [#6b6b73](Enter resume · D delete · R refresh · Esc close)[/#6b6b73]",
                id="hist-title",
            )
            yield OptionList(*self._build_options(), id="hist-list")
            with Horizontal(id="hist-buttons"):
                yield Button("Resume", id="hist-resume", variant="success")
                yield Button("Cancel", id="hist-cancel")

    def _build_options(self) -> list:
        opts: list = []
        try:
            for model_dir in sorted(os.listdir(HISTORY_DIR)):
                full = os.path.join(HISTORY_DIR, model_dir)
                if not os.path.isdir(full):
                    continue
                sessions = list_sessions(model_dir)
                for s in sessions:
                    when = s["start_time"][:19].replace("T", " ")
                    title = (
                        f"{model_dir:<30}  {when}  "
                        f"{s['message_count']:>4} msgs  T {s['temperature']:.1f}"
                    )
                    opts.append(Option(title, id=f"{model_dir}|{s['filename']}"))
        except FileNotFoundError:
            pass
        if not opts:
            opts.append(Option("(no saved sessions)", id="__none__", disabled=True))
        return opts

    def action_refresh(self) -> None:
        olist = self.query_one("#hist-list", OptionList)
        olist.clear_options()
        olist.add_options(self._build_options())

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        self._resume(event.option_id)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "hist-resume":
            olist = self.query_one("#hist-list", OptionList)
            try:
                highlighted = olist.highlighted
                opt = olist.get_option_at_index(highlighted) if highlighted is not None else None
            except Exception:
                opt = None
            if opt is not None and opt.id:
                self._resume(opt.id)
        elif event.button.id == "hist-cancel":
            self.dismiss(None)

    def action_delete(self) -> None:
        olist = self.query_one("#hist-list", OptionList)
        try:
            highlighted = olist.highlighted
            opt = olist.get_option_at_index(highlighted) if highlighted is not None else None
        except Exception:
            return
        if opt is None or not opt.id or "|" not in opt.id:
            return
        model_name, filename = opt.id.split("|", 1)
        if delete_session(model_name, filename):
            self.notify(f"Deleted {filename}", severity="warning")
            self.action_refresh()

    def _resume(self, opt_id: Optional[str]) -> None:
        if not opt_id or opt_id == "__none__" or "|" not in opt_id:
            return
        dir_name, filename = opt_id.split("|", 1)
        data = load_session_full(dir_name, filename)
        messages = data.get("messages", [])
        # The directory name is sanitized (':' → '_'), so it is NOT a valid
        # model id. The real, unsanitized name is stored in the session JSON —
        # use it, otherwise Ollama 404s on e.g. 'llama3.2_3b' vs 'llama3.2:3b'.
        model_name = data.get("model") or dir_name
        backend = data.get("backend", "")
        stream_model = data.get("stream_model", "")
        # Resolve the backend authoritatively:
        #   • A known API model id MUST run on the api backend — rebuild its
        #     api:// url (covers real, legacy, and CLI-stub saves alike).
        #   • Otherwise honour the stored backend, defaulting to ollama for
        #     legacy sessions saved before backend persistence.
        api_url = resolve_api_url(model_name)
        if api_url:
            backend, stream_model = "api", api_url
        elif not backend:
            backend = "ollama"
        self.dismiss((model_name, messages, backend, stream_model))

    def action_cancel(self) -> None:
        self.dismiss(None)
