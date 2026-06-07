"""SettingsModal — organised, colour-coded settings panel."""
from __future__ import annotations

from textual import work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Checkbox, Input, Static

from ...config import config, save_config


def _section(title: str) -> Static:
    return Static(
        f"[b][#a855f7]{title.strip()}[/#a855f7][/b]",
        classes="set-section",
    )


def _label(text: str, hint: str = "") -> Static:
    h = f"  [#6b6b73]{hint}[/#6b6b73]" if hint else ""
    return Static(f"[#a8a8b0]{text}[/#a8a8b0]{h}", classes="set-label")


class SettingsModal(ModalScreen):
    BINDINGS = [
        Binding("escape", "cancel", "Close", show=False),
        Binding("ctrl+s", "save", "Save", show=False, priority=True),
    ]

    def compose(self) -> ComposeResult:
        with Container(id="set-container"):
            yield Static(
                "[b][#a855f7]◆ Settings[/#a855f7][/b]   "
                "[#6b6b73]Ctrl+S save · Esc close[/#6b6b73]",
                id="set-title",
            )
            with VerticalScroll(id="set-scroll"):

                # ── AI / Chat ────────────────────────────────────────────
                yield _section("AI & Chat")
                yield _label("Default model", "used when launching a new session")
                yield Input(
                    value=config.default_chat_model,
                    id="set-model",
                    placeholder="e.g. qwen2.5:3b",
                )
                yield _label("Default context length (tokens)", "num_ctx sent to Ollama")
                yield Input(
                    value=str(config.default_context_length),
                    id="set-ctx",
                    placeholder="2048",
                )

                # ── Features ─────────────────────────────────────────────
                yield _section("Features")
                yield Checkbox(
                    "Tool calling",
                    value=config.tools_enabled,
                    id="set-tools",
                )
                yield _label("Tool timeout (seconds)", "max time per tool execution")
                yield Input(
                    value=str(config.tool_timeout_seconds),
                    id="set-timeout",
                    placeholder="60",
                )
                yield Checkbox(
                    "Global memory  (shared across all models)",
                    value=config.global_memory_enabled,
                    id="set-globalmem",
                )

                # ── History ──────────────────────────────────────────────
                yield _section("History")
                yield _label("Max saved sessions per model", "oldest are pruned automatically")
                yield Input(
                    value=str(config.max_history_sessions),
                    id="set-history",
                    placeholder="50",
                )

                # ── Connections ───────────────────────────────────────────
                yield _section("Connections")
                yield _label("Ollama API URL")
                yield Input(
                    value=config.ollama_api_url,
                    id="set-ollama",
                    placeholder="http://localhost:11434",
                )
                yield _label("HuggingFace token", "optional — for HF model browser")
                yield Input(
                    value=config.hf_api_token or "",
                    id="set-hf", placeholder="hf_…", password=True,
                )
                yield _label("HF models limit", "max models fetched from Hub")
                yield Input(
                    value=str(config.hf_models_limit),
                    id="set-hf-limit", placeholder="20",
                )

                # ── Cloud API providers ──────────────────────────────────
                yield _section("Cloud API Providers")
                yield _label("OpenAI API key", "for GPT-4o, o1, …")
                yield Input(
                    value=config.openai_api_key or "",
                    id="set-openai", placeholder="sk-…", password=True,
                )
                yield _label("Anthropic API key", "for Claude models")
                yield Input(
                    value=config.anthropic_api_key or "",
                    id="set-anthropic", placeholder="sk-ant-…", password=True,
                )
                yield _label("Google API key", "for Gemini models")
                yield Input(
                    value=config.google_api_key or "",
                    id="set-google", placeholder="AIza…", password=True,
                )

                # ── llama.cpp ─────────────────────────────────────────────
                yield _section("llama.cpp")
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
                yield Static("[#6b6b73]Checking connection…[/#6b6b73]", id="set-llamacpp-status")

            # ── Buttons (docked below the scroll — always visible) ───────
            with Horizontal(id="set-buttons"):
                yield Button("Save", id="set-save", variant="success")
                yield Button("Cancel", id="set-cancel")

    # ── Event handlers ───────────────────────────────────────────────────

    def on_mount(self) -> None:
        self._probe_llamacpp()

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
        config.global_memory_enabled  = self.query_one("#set-globalmem",Checkbox).value
        config.default_context_length = max(256, _int("#set-ctx", config.default_context_length))
        config.tool_timeout_seconds   = _int("#set-timeout", config.tool_timeout_seconds)
        config.max_history_sessions   = _int("#set-history",  config.max_history_sessions)
        config.hf_models_limit        = _int("#set-hf-limit", config.hf_models_limit)

        ollama = self.query_one("#set-ollama", Input).value.strip()
        if ollama:
            config.ollama_api_url = ollama

        model = self.query_one("#set-model", Input).value.strip()
        if model:
            config.default_chat_model = model

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
