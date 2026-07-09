"""SettingsModal — tabbed, colour-coded settings panel.

Four small pages (General · Performance · Connections · API Keys) instead of
one long scroll. All widget ids are stable — action_save reads them wherever
they live, active tab or not (TabbedContent keeps every pane mounted).
"""
from __future__ import annotations

from textual import work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import (Button, Checkbox, Input, Select, Static,
                             TabbedContent, TabPane)

from ...config import config, save_config


def _label(text: str, hint: str = "") -> Static:
    h = f"  [#6b6b73]{hint}[/#6b6b73]" if hint else ""
    return Static(f"[#a8a8b0]{text}[/#a8a8b0]{h}", classes="set-label")


def _note(markup: str) -> Static:
    return Static(f"[#6b6b73]{markup}[/#6b6b73]", classes="set-note")


class SettingsModal(ModalScreen):
    BINDINGS = [
        Binding("escape", "cancel", "Close", show=False),
        Binding("ctrl+s", "save", "Save", show=False, priority=True),
    ]

    def compose(self) -> ComposeResult:
        with Container(id="set-container"):
            yield Static(
                "[b][#a855f7]◆ Settings[/#a855f7][/b]   "
                "[#6b6b73]◀ ▶ switch tab · Tab next field · Ctrl+S save · Esc close[/#6b6b73]",
                id="set-title",
            )
            with TabbedContent(id="set-tabs"):

                # ── General — model, chat behaviour ──────────────────────
                with TabPane("General", id="set-tab-general"):
                    with VerticalScroll(classes="set-pane"):
                        yield _label("Default model", "used for new chats")
                        _model_opts = self._model_options()
                        if _model_opts:
                            _vals = [v for _, v in _model_opts]
                            _cur = config.default_chat_model
                            yield Select(
                                _model_opts,
                                value=(_cur if _cur in _vals else Select.BLANK),
                                id="set-model",
                                allow_blank=True,
                                prompt="Select a model…",
                            )
                        else:
                            # No Ollama models detected — keep it editable.
                            yield Input(
                                value=config.default_chat_model,
                                id="set-model",
                                placeholder="e.g. qwen2.5:3b  (no Ollama models detected)",
                            )
                        yield Checkbox(
                            "Memory — inject saved facts into chats",
                            value=config.memory_enabled,
                            id="set-globalmem",
                        )
                        yield Checkbox(
                            "Tool calling — let models run tools",
                            value=config.tools_enabled,
                            id="set-tools",
                        )
                        yield _label("Tool timeout (seconds)", "max time per tool run")
                        yield Input(
                            value=str(config.tool_timeout_seconds),
                            id="set-timeout",
                            placeholder="60",
                        )
                        yield _label("Saved sessions per model",
                                     "oldest are pruned automatically")
                        yield Input(
                            value=str(config.max_history_sessions),
                            id="set-history",
                            placeholder="50",
                        )

                # ── Performance — GPU / context ──────────────────────────
                with TabPane("Performance", id="set-tab-perf"):
                    with VerticalScroll(classes="set-pane"):
                        yield Static("[#6b6b73]Detecting hardware…[/#6b6b73]",
                                     id="set-gpu-info")
                        yield _label("Default context length (tokens)",
                                     "num_ctx — larger contexts use more VRAM")
                        yield Input(
                            value=str(config.default_context_length),
                            id="set-ctx",
                            placeholder="2048",
                        )
                        yield _label("GPU layers (num_gpu)",
                                     "0 = auto · 999 = force all layers on GPU")
                        yield Input(
                            value=str(config.ollama_num_gpu),
                            id="set-num-gpu",
                            placeholder="0",
                        )
                        yield _note(
                            "If a model runs on CPU despite a GPU: lower the "
                            "context length or set GPU layers to 999.")

                # ── Connections — local backends ─────────────────────────
                with TabPane("Connections", id="set-tab-conn"):
                    with VerticalScroll(classes="set-pane"):
                        yield _label("Ollama API URL")
                        yield Input(
                            value=config.ollama_api_url,
                            id="set-ollama",
                            placeholder="http://localhost:11434",
                        )
                        yield Checkbox(
                            "Enable llama.cpp backend",
                            value=config.llamacpp_enabled,
                            id="set-llamacpp-enabled",
                        )
                        yield _label("llama-server URL", "OpenAI-compatible endpoint")
                        yield Input(
                            value=config.llamacpp_url,
                            id="set-llamacpp-url",
                            placeholder="http://localhost:8080",
                        )
                        yield Static("[#6b6b73]Checking connection…[/#6b6b73]",
                                     id="set-llamacpp-status")

                # ── API Keys — cloud providers ───────────────────────────
                with TabPane("API Keys", id="set-tab-keys"):
                    with VerticalScroll(classes="set-pane"):
                        yield _note("Optional — only needed for cloud models. "
                                    "Stored locally in ~/.aihub/config.yaml.")
                        yield _label("Anthropic API key", "Claude models")
                        yield Input(
                            value=config.anthropic_api_key or "",
                            id="set-anthropic", placeholder="sk-ant-…", password=True,
                        )
                        yield _label("OpenAI API key", "GPT-4o, o1, …")
                        yield Input(
                            value=config.openai_api_key or "",
                            id="set-openai", placeholder="sk-…", password=True,
                        )
                        yield _label("Google API key", "Gemini models")
                        yield Input(
                            value=config.google_api_key or "",
                            id="set-google", placeholder="AIza…", password=True,
                        )
                        yield _label("HuggingFace token", "optional — HF model browser")
                        yield Input(
                            value=config.hf_api_token or "",
                            id="set-hf", placeholder="hf_…", password=True,
                        )
                        yield _label("HF models limit", "max models fetched from Hub")
                        yield Input(
                            value=str(config.hf_models_limit),
                            id="set-hf-limit", placeholder="20",
                        )

            # ── Buttons (docked below the tabs — always visible) ─────────
            with Horizontal(id="set-buttons"):
                yield Button("Save", id="set-save", variant="success")
                yield Button("Cancel", id="set-cancel")

    # ── Event handlers ───────────────────────────────────────────────────

    def on_mount(self) -> None:
        self._probe_llamacpp()
        self._probe_gpu()

    @work(thread=True, exclusive=True, group="gpu-probe")
    def _probe_gpu(self) -> None:
        """Fill the Performance tab's hardware line (runs subprocesses)."""
        from ...hardware import get_gpu_info
        gpu = get_gpu_info()
        total = (gpu.get("vram_total_mb") or 0) / 1024.0
        free = (gpu.get("vram_free_mb") or 0) / 1024.0
        if total > 0:
            text = (f"[#22c55e]●[/#22c55e] [#a8a8b0]{gpu.get('model', 'GPU')}[/#a8a8b0]"
                    f"  [#6b6b73]{total:.1f} GB VRAM · {free:.1f} GB free[/#6b6b73]")
        else:
            text = "[#6b6b73]○ No dedicated GPU detected — models run on CPU.[/#6b6b73]"
        try:
            self.app.call_from_thread(
                lambda: self.query_one("#set-gpu-info", Static).update(text)
            )
        except Exception:
            pass

    def _model_options(self) -> list:
        """(label, value) pairs of downloaded models for the Default-model
        dropdown. Empty list → the field falls back to a text input."""
        names = []
        try:
            from ...ollama_client import get_local_model_sizes, is_ollama_running
            if is_ollama_running():
                names = sorted(get_local_model_sizes().keys())
        except Exception:
            names = []
        cur = config.default_chat_model
        # Only show a dropdown when real installed models exist; otherwise the
        # caller falls back to an editable Input. If a default isn't in the list,
        # surface it too so the current value stays selectable.
        if names and cur and cur not in names:
            names = [cur] + names
        return [(n, n) for n in names]

    @work(thread=True, exclusive=True, group="llamacpp-probe")
    def _probe_llamacpp(self) -> None:
        from ...llamacpp_client import is_llamacpp_running, get_loaded_model
        ok = is_llamacpp_running()
        model = get_loaded_model() if ok else ""
        if ok:
            status = (f"[#22c55e]● connected[/#22c55e]"
                      + (f" — [#a855f7]{model}[/#a855f7]" if model else " [#6b6b73](no model loaded)[/#6b6b73]"))
        else:
            status = "[#ff6e6e]○ not reachable[/#ff6e6e]  [#6b6b73]start llama-server first[/#6b6b73]"
        try:
            self.app.call_from_thread(
                lambda: self.query_one("#set-llamacpp-status", Static).update(status)
            )
        except Exception:
            pass

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "set-save":
            self.action_save()
        elif event.button.id == "set-cancel":
            self.dismiss(None)

    def action_save(self) -> None:
        def _int(widget_id: str, fallback: int) -> int:
            try:
                return max(1, int(self.query_one(widget_id, Input).value))
            except (ValueError, TypeError):
                return fallback

        config.tools_enabled          = self.query_one("#set-tools",    Checkbox).value
        config.memory_enabled         = self.query_one("#set-globalmem",Checkbox).value
        config.default_context_length = max(256, _int("#set-ctx", config.default_context_length))
        try:
            config.ollama_num_gpu = max(0, int(self.query_one("#set-num-gpu", Input).value))
        except (ValueError, TypeError):
            pass
        config.tool_timeout_seconds   = _int("#set-timeout", config.tool_timeout_seconds)
        config.max_history_sessions   = _int("#set-history",  config.max_history_sessions)
        config.hf_models_limit        = _int("#set-hf-limit", config.hf_models_limit)

        ollama = self.query_one("#set-ollama", Input).value.strip()
        if ollama:
            config.ollama_api_url = ollama

        # Works whether #set-model is a Select (value=str|BLANK) or the Input
        # fallback (value=str). Only a real non-empty string updates the default.
        model = getattr(self.query_one("#set-model"), "value", "")
        if isinstance(model, str) and model.strip():
            config.default_chat_model = model.strip()

        hf = self.query_one("#set-hf", Input).value.strip()
        config.hf_api_token = hf

        config.openai_api_key    = self.query_one("#set-openai", Input).value.strip()
        config.anthropic_api_key = self.query_one("#set-anthropic", Input).value.strip()
        config.google_api_key    = self.query_one("#set-google", Input).value.strip()

        config.llamacpp_enabled = self.query_one("#set-llamacpp-enabled", Checkbox).value
        llamacpp_url = self.query_one("#set-llamacpp-url", Input).value.strip()
        if llamacpp_url:
            config.llamacpp_url = llamacpp_url

        try:
            save_config(config)
            self.notify("Settings saved.", severity="information")
        except Exception as exc:
            self.notify(f"Save failed: {exc}", severity="error")
            return
        self.dismiss(None)

    def action_cancel(self) -> None:
        self.dismiss(None)
