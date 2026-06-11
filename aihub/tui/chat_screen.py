"""ChatScreen — the only persistent screen.

Owns the SessionState, the ChatLog, the ChatInput, and the StatusBar.
Modal overlays (model picker, history, memory, hardware, settings, command
palette) land in Phase D and are pushed by bindings.

Phase C wires the chat stream worker. Until the model-picker modal lands in
Phase D, you can pick a model with the temporary `/model <name>` command.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List

from textual import work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.reactive import reactive
from textual.screen import Screen
from textual.widgets import Static

from ..chat import (
    Done, Error, RoundCompleted, TextChunk,
    ToolCallRequested, ToolCallResult, Usage,
    finalize_session, start_session,
)
from ..config import config
from ..memory import (
    build_system_prompt, clear_memory, load_memory, update_memory_entry,
)
from ..ollama_client import unload_model
from ..slash import (
    HELP_TEXT, KIND_CLEAR, KIND_HELP, KIND_HISTORY_BROWSE,
    KIND_MEMORY_CLEAR, KIND_MEMORY_EXTRACT, KIND_MEMORY_SAVE,
    KIND_MEMORY_SHOW, KIND_NEW_CHAT, KIND_TOOLS_INFO, KIND_UNKNOWN, KIND_USAGE,
    parse_slash,
)
from ..tools import get_tools_description
from .messages import (
    ChatEventReceived, InputSubmitted, LlamaCppStatusChanged,
    MemoryUpdated, OllamaStatusChanged,
    SlashNavigate, SlashQuery, StreamCancelRequested,
)
from .modals import (
    CommandPaletteModal, ContextConfigModal, HardwareModal, HelpModal,
    HistoryModal, MemoryModal, ModelPickerModal, PermissionModal, SettingsModal,
)
from ..agent import agent_capable, system_prompt as agent_system_prompt, permission_for
from ..tools import AGENT_TOOLS_SCHEMA
from .state import SessionState
from .widgets import ChatInput, ChatLog, FooterBar, SlashSuggest, StatusBar
from .widgets.sidebar import Sidebar
from . import workers


class ChatScreen(Screen):
    # NOTE: ctrl+m = Enter, ctrl+h = Backspace, ctrl+i = Tab at the terminal byte
    # level — those are unusable as bindings. Using safe alternatives instead.
    BINDINGS = [
        Binding("ctrl+p", "command_palette", "Palette", show=False, priority=True),
        Binding("ctrl+o", "model_picker", "Models",  show=False, priority=True),  # was ctrl+m
        Binding("ctrl+r", "history",      "History", show=False, priority=True),  # was ctrl+h
        Binding("ctrl+e", "memory",       "Memory",  show=False, priority=True),
        Binding("ctrl+b", "hardware",     "Hardware",show=False, priority=True),  # was ctrl+i
        Binding("ctrl+comma", "settings", "Settings",show=False, priority=True),
        Binding("ctrl+l", "clear_chat",   "Clear",   show=False, priority=True),
        Binding("ctrl+n", "new_chat",     "New",     show=False, priority=True),
        Binding("ctrl+s", "save_session", "Save",    show=False, priority=True),
        Binding("ctrl+t", "toggle_tools", "Tools",   show=False, priority=True),
        Binding("ctrl+g", "agent",        "Agent",   show=False, priority=True),
        Binding("f2",     "toggle_agent_submode", "Plan/Build", show=False, priority=True),
        Binding("escape", "cancel_stream","Cancel",  show=False),
        Binding("f1",     "help",         "Help",    show=False, priority=True),
        Binding("question_mark", "help",  "Help",    show=False),
        # Single-key nav shortcuts (vim-style) — fire only when the chat input
        # is NOT focused, since the TextArea consumes printable keys while typing.
        # The Ctrl-combos above still work while typing.
        Binding("n", "new_chat",        show=False),
        Binding("a", "agent",           show=False),
        Binding("m", "model_picker",    show=False),
        Binding("h", "history",         show=False),
        Binding("e", "memory",          show=False),
        Binding("w", "hardware",        show=False),
        Binding("s", "settings",        show=False),
        Binding("p", "command_palette", show=False),
        Binding("ctrl+q", "quit",         "Quit",    show=False, priority=True),
    ]

    # Smallest terminal the UI stays usable at. Below this, a guard overlay
    # replaces the main layout with a "resize" message.
    MIN_WIDTH = 80
    MIN_HEIGHT = 18

    # Reactive state
    current_model = reactive("(no model)")
    context_length = reactive(2048)
    temperature = reactive(0.7)
    memory_enabled = reactive(False)
    tools_enabled = reactive(True)
    streaming = reactive(False)
    ollama_online = reactive(False)

    def __init__(self) -> None:
        super().__init__()
        self.state = SessionState(
            temperature=0.7,
            context_length=config.default_context_length,
            tools_enabled=config.tools_enabled,
        )
        self.context_length = config.default_context_length
        self.tools_enabled = config.tools_enabled
        # Set when the user cancels. Cleared at the start of each new turn.
        # While set, late ChatEventReceived messages (text/tool) are ignored;
        # Done is still processed so streaming flag is reset cleanly.
        self._cancelled = False

    def compose(self) -> ComposeResult:
        from textual.containers import Horizontal as HBox, Vertical as VBox
        yield StatusBar()
        with HBox(id="main-layout"):
            yield Sidebar()
            with VBox(id="chat-area"):
                yield ChatLog(id="chat-log")
                yield SlashSuggest()
                yield ChatInput()
                yield Static(
                    "[#6b6b73]↵ send · ⇧↵ newline · ^R rerun[/#6b6b73]",
                    id="input-hint",
                )
        yield FooterBar()
        # Overlay shown when the terminal is too small for the UI to be usable.
        yield Static("", id="too-small")

    def on_resize(self, event) -> None:
        self._apply_size_guard(event.size.width, event.size.height)

    def _apply_size_guard(self, width: int, height: int) -> None:
        """Hide the main UI behind a 'resize' message when the terminal is too
        small for everything to be visible/usable."""
        too_small = width < self.MIN_WIDTH or height < self.MIN_HEIGHT
        try:
            guard = self.query_one("#too-small", Static)
            main = self.query_one("#main-layout")
            bar = self.query_one(StatusBar)
            foot = self.query_one(FooterBar)
        except Exception:
            return
        guard.display = too_small
        main.display = not too_small
        bar.display = not too_small
        foot.display = not too_small
        if too_small:
            guard.update(
                "[b]Terminal too small[/b]\n\n"
                f"Resize to at least [b]{self.MIN_WIDTH}×{self.MIN_HEIGHT}[/b]\n"
                f"[#6b6b73]current: {width}×{height}[/#6b6b73]"
            )

    @work(thread=True, exclusive=True, group="usage-poll")
    def _refresh_usage(self) -> None:
        # nvidia-smi/psutil run off the UI thread (subprocess can block).
        from ..hardware import get_gpu_usage, get_cpu_usage
        g = get_gpu_usage()
        cpu = get_cpu_usage()

        def apply() -> None:
            self._sync_status(
                gpu_util=g.get("util_percent", -1.0) if g else -1.0,
                vram_used_gb=(g.get("vram_used_mb", 0) / 1024.0) if g else 0.0,
                vram_total_gb=(g.get("vram_total_mb", 0) / 1024.0) if g else 0.0,
                cpu_percent=cpu,
            )
        try:
            self.app.call_from_thread(apply)
        except Exception:
            pass

    def on_mount(self) -> None:
        self._apply_size_guard(self.size.width, self.size.height)
        # Live device-usage poll (GPU util/VRAM or CPU%) — off-thread.
        self._refresh_usage()
        self.set_interval(4.0, self._refresh_usage)
        log = self.query_one(ChatLog)
        log.add_system(
            "[b][#a855f7]Welcome to AIHub.[/#a855f7][/b]  "
            "[#a855f7]Ctrl+O[/#a855f7] models  ·  "
            "[#a855f7]Ctrl+P[/#a855f7] palette  ·  "
            "[#a855f7]Ctrl+R[/#a855f7] history  ·  "
            "[#a855f7]Ctrl+E[/#a855f7] memory  ·  "
            "[#a855f7]Ctrl+B[/#a855f7] hardware  ·  "
            "[#a855f7]F1[/#a855f7] help  ·  "
            "[#a855f7]Ctrl+Q[/#a855f7] quit"
        )
        self._poll_ollama_worker()
        self.set_interval(15.0, self._poll_ollama_worker)
        self._sync_meta()

    # ── Watcher helpers ──────────────────────────────────────────────────

    def _refresh_header(self) -> None:
        # CONNECTED (green) only when a model is actually selected; OFFLINE (red)
        # otherwise.
        online = bool(self.current_model)
        try:
            self.query_one(Sidebar).update_model(
                self.current_model, self.context_length, online)
        except Exception:
            pass

    def _sync_status(self, **changes) -> None:
        # Push the same attributes to both the top header and the bottom bar.
        for bar_cls in (StatusBar, FooterBar):
            try:
                bar = self.query_one(bar_cls)
            except Exception:
                continue
            for key, value in changes.items():
                setattr(bar, key, value)
            try:
                bar.refresh_status()
            except Exception:
                pass

    def _sync_meta(self) -> None:
        """Refresh the header's session title + message count from state."""
        msgs = [m for m in self.state.messages
                if m.get("role") in ("user", "assistant")]
        title = "new session"
        for m in self.state.messages:
            if m.get("role") == "user" and m.get("content", "").strip():
                t = " ".join(m["content"].split())
                title = t if len(t) <= 42 else t[:41] + "…"
                break
        self._sync_status(session_title=title, message_count=len(msgs))

    def watch_current_model(self, _old: str, new: str) -> None:
        self._refresh_header()
        self._sync_status(model_name=new)

    def watch_context_length(self, _old: int, new: int) -> None:
        self._refresh_header()
        self._sync_status(context_length=new)

    def watch_temperature(self, _old: float, new: float) -> None:
        self._sync_status(temperature=new)

    def watch_memory_enabled(self, _old: bool, new: bool) -> None:
        self._sync_status(memory_enabled=new)

    def watch_tools_enabled(self, _old: bool, new: bool) -> None:
        self._sync_status(tools_enabled=new)

    def watch_streaming(self, _old: bool, new: bool) -> None:
        self._sync_status(streaming=new)
        try:
            inp = self.query_one(ChatInput)
            inp.disabled = new
            inp.set_class(new, "disabled")
            if not new:
                inp.focus()
        except Exception:
            pass

    def watch_ollama_online(self, _old: bool, new: bool) -> None:
        self._sync_status(ollama_online=new)

    # ── Backend status poll ──────────────────────────────────────────────

    @work(thread=True, exclusive=True, group="backends-poll")
    def _poll_ollama_worker(self) -> None:
        workers.poll_backends(self)

    def on_ollama_status_changed(self, message: OllamaStatusChanged) -> None:
        self.ollama_online = message.online

    def on_llama_cpp_status_changed(self, message: LlamaCppStatusChanged) -> None:
        self._sync_status(llamacpp_online=message.online, llamacpp_model=message.model_name)

    # ── Input handling ───────────────────────────────────────────────────

    def on_input_submitted(self, message: InputSubmitted) -> None:
        text = message.text.strip()
        if not text:
            return
        log = self.query_one(ChatLog)

        if text.startswith("/"):
            self._handle_slash(text, log)
            return

        if self.current_model in ("(no model)", "", None):
            log.add_system(
                "No model selected. Type [b]/model <name>[/b] to pick one. "
                "(Modal picker lands in Phase D.)"
            )
            return
        if not self.ollama_online:
            log.add_system("Ollama is offline — start `ollama serve` and try again.")
            return
        if self.streaming:
            return

        log.add_user(text)
        self.state.messages.append({"role": "user", "content": text})
        self._sync_meta()
        self._start_stream()

    # ── Slash autocomplete ───────────────────────────────────────────────

    def on_slash_query(self, message: SlashQuery) -> None:
        """ChatInput text changed — show/update/hide the slash popup."""
        popup = self.query_one(SlashSuggest)
        inp = self.query_one(ChatInput)
        text = message.text
        # Don't show popup when text ends with space (command accepted, typing args).
        if text and text.startswith("/") and not text.endswith(" "):
            popup.update_query(text)
            inp._slash_popup_open = popup.is_visible
        else:
            popup.hide()
            inp._slash_popup_open = False

    def on_slash_navigate(self, message: SlashNavigate) -> None:
        """User pressed Up/Down/Tab/Enter/Esc while popup is open."""
        popup = self.query_one(SlashSuggest)
        inp = self.query_one(ChatInput)
        key = message.key
        if key == "up":
            popup.move_up()
        elif key == "down":
            popup.move_down()
        elif key in ("enter", "tab"):
            popup.accept()          # fires SlashSuggest.Accepted
        elif key == "escape":
            popup.hide()
            inp._slash_popup_open = False

    def on_slash_suggest_accepted(self, message: SlashSuggest.Accepted) -> None:
        """User accepted a suggestion — fill the input and close the popup."""
        popup = self.query_one(SlashSuggest)
        inp = self.query_one(ChatInput)
        # Close popup BEFORE loading text so the text-change event doesn't reopen it.
        popup.hide()
        inp._slash_popup_open = False
        inp._accepting_suggestion = True   # guard against re-triggering in on_slash_query
        # Put the command in the input with a trailing space ready for args.
        inp.load_text(message.command + " ")
        inp._accepting_suggestion = False
        inp.focus()
        try:
            inp.move_cursor(inp.get_cursor_line_end_location())
        except Exception:
            pass

    # ── Chat stream worker driver ────────────────────────────────────────

    @work(thread=True, exclusive=True, group="chat-stream")
    def _start_stream(self) -> None:
        self._cancelled = False
        self.app.call_from_thread(self._set_streaming, True)
        # Resolve backend stream function and the id to send.
        stream_fn = None
        stream_model = self.current_model
        if self.state.backend == "llamacpp":
            from ..llamacpp_client import chat_stream as llamacpp_stream
            stream_fn = llamacpp_stream
        elif self.state.backend == "api":
            from ..api_client import chat_stream as api_stream
            stream_fn = api_stream
            stream_model = self.state.stream_model or self.current_model
        agent = self.state.mode == "agent"
        approve_fn = self._make_approve_fn() if agent else None
        tools_schema = AGENT_TOOLS_SCHEMA if agent else None
        # Agent mode always uses tools; chat keeps the per-backend toggle.
        tools_on = True if agent else (self.tools_enabled and self.state.backend != "api")
        workers.stream_chat(
            self,
            stream_model,
            self.state.messages,
            temperature=self.temperature,
            context_length=self.context_length,
            tools_enabled=tools_on,
            stream_fn=stream_fn,
            approve_fn=approve_fn,
            tools_schema=tools_schema,
        )

    def _set_streaming(self, value: bool) -> None:
        self.streaming = value

    def on_chat_event_received(self, msg: ChatEventReceived) -> None:
        log = self.query_one(ChatLog)
        event = msg.event
        # Always honour Done — the worker fires it in its finally clause and
        # we rely on it to reset the streaming flag.
        if isinstance(event, Done):
            log.end_assistant()
            self.streaming = False
            self._cancelled = False
            self._sync_meta()
            return
        # Drop late events after cancel.
        if self._cancelled:
            return
        if isinstance(event, TextChunk):
            log.append_assistant_text(event.text)
        elif isinstance(event, ToolCallRequested):
            log.end_assistant()
            log.start_tool_panel(event.call_id, event.name, event.arguments)
        elif isinstance(event, ToolCallResult):
            log.complete_tool_panel(
                event.call_id, event.result, event.duration_ms, error=event.error,
            )
        elif isinstance(event, RoundCompleted):
            log.end_assistant()
        elif isinstance(event, Usage):
            self.state.session_tokens += event.prompt_tokens + event.completion_tokens
            self.state.ctx_used = event.prompt_tokens
            self._sync_status(
                ctx_used=event.prompt_tokens,
                ctx_max=self.context_length,
                session_tokens=self.state.session_tokens,
            )
        elif isinstance(event, Error):
            colour = "#ff6e6e" if event.fatal else "#ffb454"
            log.add_system(f"[{colour}]{event.message}[/{colour}]")
            if event.fatal:
                self.streaming = False

    # ── Slash command dispatcher ─────────────────────────────────────────

    def _handle_slash(self, raw: str, log: ChatLog) -> None:
        # Stop-gap commands not in slash.py
        if raw.startswith("/model"):
            self._handle_model_command(raw, log)
            return
        if raw.startswith("/quit") or raw == "/q" or raw == "/exit":
            self.app.exit()
            return

        result = parse_slash(raw)
        kind = result.kind

        if kind == KIND_HELP:
            log.add_system(HELP_TEXT.strip())
        elif kind == KIND_TOOLS_INFO:
            log.add_system(get_tools_description())
        elif kind == KIND_NEW_CHAT:
            self.action_new_chat()
        elif kind == KIND_CLEAR:
            self.action_clear_chat()
        elif kind == KIND_MEMORY_SHOW:
            mem = load_memory()
            if mem:
                log.add_system(f"Memory:\n\n{mem}")
            else:
                log.add_system(
                    "No memory stored. Use /memory save <key> <value> to add."
                )
        elif kind == KIND_MEMORY_SAVE:
            k = result.payload["key"]
            v = result.payload["value"]
            update_memory_entry(k, v)
            self._refresh_memory()
            log.add_system(f"Memory saved: {k} → {v}")
        elif kind == KIND_MEMORY_CLEAR:
            cleared = clear_memory()
            self._refresh_memory()
            log.add_system(
                "Memory cleared." if cleared else "No memory file found."
            )
        elif kind == KIND_MEMORY_EXTRACT:
            if self.current_model in ("(no model)", "", None):
                log.add_system("No model selected — needed to summarize the chat.")
            else:
                log.add_system("Extracting facts → memory…")
                self._extract_memory_worker()
        elif kind == KIND_HISTORY_BROWSE:
            self.action_history()
        elif kind == KIND_USAGE:
            log.add_system(result.message or "Bad command usage.")
        elif kind == KIND_UNKNOWN:
            log.add_system(result.message or f"Unknown command: {raw}")

    def _handle_model_command(self, raw: str, log: ChatLog) -> None:
        parts = raw.split(maxsplit=1)
        if len(parts) < 2 or not parts[1].strip():
            log.add_system("Usage: /model <name>")
            return
        new_model = parts[1].strip()
        # finalize previous session
        if self.state.model_name and self.state.messages:
            saved = finalize_session(
                self.state.model_name,
                self.state.messages,
                self.temperature,
                self.state.start_time,
                backend=self.state.backend,
                stream_model=self.state.stream_model,
            )
            if saved:
                log.add_system(f"Saved previous session: {saved}")
            try:
                unload_model(self.state.model_name)
            except Exception:
                pass
        # reset for new model
        self.state.reset_for(new_model, self.context_length)
        new_messages = start_session(new_model)
        self.state.messages = new_messages
        has_memory = bool(config.memory_enabled)
        self.state.memory_enabled = has_memory
        self.current_model = new_model
        self.memory_enabled = has_memory
        log.clear_all()
        _mc = '#22c55e' if has_memory else '#6b6b73'
        log.add_system(
            f"Model: [#a855f7]{new_model}[/#a855f7]  ·  "
            "memory [" + _mc + "]" + ('on ✓' if has_memory else 'off') + "[/" + _mc + "]  ·  "
            f"ctx {self.context_length}  ·  T {self.temperature:.1f}"
        )

    @work(thread=True, exclusive=False, group="memory-extract")
    def _extract_memory_worker(self) -> None:
        workers.extract_memory(self, self.current_model, list(self.state.messages))

    def on_memory_updated(self, message: MemoryUpdated) -> None:
        log = self.query_one(ChatLog)
        if message.summary and message.summary.startswith("Error:"):
            log.add_system(f"[#ff6e6e]{message.summary}[/#ff6e6e]")
        else:
            log.add_system(f"Memory updated:\n{message.summary or ''}")
        self._refresh_memory()

    # ── Modal actions ────────────────────────────────────────────────────

    def action_command_palette(self) -> None:
        self.app.push_screen(CommandPaletteModal(), self._on_palette_pick)

    def _on_palette_pick(self, action_id: str | None) -> None:
        if not action_id:
            return
        mapping = {
            "model_picker":     self.action_model_picker,
            "clear_chat":       self.action_clear_chat,
            "new_chat":         self.action_new_chat,
            "agent":            self.action_agent,
            "save_session":     self.action_save_session,
            "history":          self.action_history,
            "memory":           self.action_memory,
            "memoryadd":        self._palette_memoryadd,
            "hardware":         self.action_hardware,
            "settings":         self.action_settings,
            "toggle_tools":     self.action_toggle_tools,
            "help":             self.action_help,
            "quit":             self.action_quit,
        }
        fn = mapping.get(action_id)
        if fn:
            fn()

    def _palette_memoryadd(self) -> None:
        if self.current_model in ("(no model)", "", None):
            self.query_one(ChatLog).add_system(
                "No model selected — needed to summarize the chat."
            )
            return
        self.query_one(ChatLog).add_system("Extracting facts → memory…")
        self._extract_memory_worker()

    def _record_recent(self, model_name: str) -> None:
        """Track recently-used models (most-recent first, capped) for the picker."""
        if not model_name or model_name in ("(no model)", ""):
            return
        try:
            from ..config import save_config
            rec = [m for m in (config.recent_models or []) if m != model_name]
            rec.insert(0, model_name)
            config.recent_models = rec[:8]
            save_config(config)
        except Exception:
            pass

    def action_model_picker(self) -> None:
        # Load registry on demand from cli.py's helper. Cheap; ~104 entries.
        from ..cli import load_registry_models
        try:
            registry = load_registry_models()
        except Exception as exc:
            self.query_one(ChatLog).add_system(f"[#ff6e6e]Could not load registry: {exc}[/#ff6e6e]")
            return
        self.app.push_screen(ModelPickerModal(registry), self._on_model_picked)

    def _on_model_picked(self, result) -> None:
        if not result:
            return
        # Picker returns (model_name, ctx, backend).
        if len(result) == 3:
            model_name, ctx, backend = result
        else:
            model_name, ctx = result
            backend = "ollama"
        self.context_length = ctx
        if backend == "api":
            # model_name is the api:// url; derive a friendly display label.
            from ..api_client import parse_api_url
            provider, api_model = parse_api_url(model_name)
            self._switch_model(api_model, backend="api", stream_model=model_name)
        else:
            self._switch_model(model_name, backend=backend)

    def _switch_model(self, model_name: str, backend: str = "ollama",
                      stream_model: str = "") -> None:
        log = self.query_one(ChatLog)
        if self.state.model_name and self.state.messages:
            try:
                saved = finalize_session(
                    self.state.model_name, self.state.messages,
                    self.temperature, self.state.start_time,
                    backend=self.state.backend, stream_model=self.state.stream_model,
                )
                if saved:
                    log.add_system(f"Saved previous session: {saved}")
            except Exception:
                pass
            # Only Ollama supports unload; llama.cpp manages its own model.
            if self.state.backend == "ollama":
                try:
                    unload_model(self.state.model_name)
                except Exception:
                    pass
        self.state.reset_for(model_name, self.context_length)
        self.state.backend = backend
        self.state.stream_model = stream_model
        new_messages = start_session(model_name)
        self.state.messages = new_messages
        has_memory = bool(config.memory_enabled)
        self.state.memory_enabled = has_memory
        self.current_model = model_name
        self.memory_enabled = has_memory
        self._record_recent(model_name)
        log.clear_all()
        _mc = '#22c55e' if has_memory else '#6b6b73'
        _bk = f"  ·  [#a855f7]{backend}[/#a855f7]" if backend in ("llamacpp", "api") else ""
        log.add_system(
            f"Model: [#a855f7]{model_name}[/#a855f7]  ·  "
            "memory [" + _mc + "]" + ('on ✓' if has_memory else 'off') + "[/" + _mc + "]  ·  "
            f"ctx {self.context_length}  ·  T {self.temperature:.1f}" + _bk
        )

    def action_history(self) -> None:
        self.app.push_screen(HistoryModal(), self._on_history_pick)

    def _on_history_pick(self, result) -> None:
        if not result:
            return
        model_name, messages, backend, stream_model = result
        # Apply: switch model context (with the saved backend), then replace
        # messages. Without the backend a Claude/API or llama.cpp session would
        # stream through Ollama and fail with "model not loaded".
        self._switch_model(model_name, backend=backend, stream_model=stream_model)
        # Replace system + append loaded non-system messages.
        existing_system = [m for m in self.state.messages if m.get("role") == "system"]
        self.state.messages = existing_system + [
            m for m in messages if m.get("role") != "system"
        ]
        # Re-render chat log from messages.
        log = self.query_one(ChatLog)
        log.clear_all()
        for m in self.state.messages:
            role = m.get("role")
            content = m.get("content", "")
            if not content:
                continue
            if role == "user":
                log.add_user(content)
            elif role == "assistant":
                log.begin_assistant()
                log.append_assistant_text(content)
                log.end_assistant()
            elif role == "tool":
                log.add_system(f"[#88a0a8]tool result:[/#88a0a8] {content[:200]}")
        log.add_system(f"Resumed {len(self.state.messages)} messages.")

    def action_memory(self) -> None:
        self.app.push_screen(MemoryModal(), self._refresh_memory)

    def action_hardware(self) -> None:
        self.app.push_screen(HardwareModal())

    def action_settings(self) -> None:
        self.app.push_screen(SettingsModal(), self._refresh_memory)

    def _refresh_memory(self, _result=None) -> None:
        # Reflect the current memory setting/content immediately: update the
        # indicator and rebuild the live session's system prompt so toggling
        # memory in Settings, or editing it, takes effect without a restart.
        self.memory_enabled = bool(config.memory_enabled)
        if self.state.mode != "agent":   # agent mode owns its own system prompt
            sp = build_system_prompt()
            msgs = self.state.messages
            if msgs and msgs[0].get("role") == "system":
                msgs[0]["content"] = sp
            elif sp:
                msgs.insert(0, {"role": "system", "content": sp})

    def action_help(self) -> None:
        self.app.push_screen(HelpModal())

    # ── Misc actions ─────────────────────────────────────────────────────

    def action_clear_chat(self) -> None:
        # Keep system messages (memory injection) so the next turn still has context.
        self.state.messages = [m for m in self.state.messages if m.get("role") == "system"]
        log = self.query_one(ChatLog)
        log.clear_all()
        log.add_system("Chat cleared.")

    def action_new_chat(self) -> None:
        """Save current session (if any messages) then start a fresh one."""
        log = self.query_one(ChatLog)
        if self.state.model_name and any(
            m.get("role") == "user" for m in self.state.messages
        ):
            saved = finalize_session(
                self.state.model_name, self.state.messages,
                self.temperature, self.state.start_time,
                backend=self.state.backend, stream_model=self.state.stream_model,
            )
            if saved:
                log.add_system(f"[#a855f7]Session saved.[/#a855f7]")
        # Rebuild messages with fresh memory injection
        self.state.messages = start_session(self.state.model_name or "")
        self.state.start_time = __import__("datetime").datetime.now()
        has_memory = bool(config.memory_enabled)
        self.memory_enabled = has_memory
        log.clear_all()
        log.add_system(
            "[b][#a855f7]New chat started.[/#a855f7][/b]  "
            f"Model: [#a855f7]{self.current_model or '(none)'}[/#a855f7]"
        )
        self._sync_meta()

    def action_save_session(self) -> None:
        log = self.query_one(ChatLog)
        if not self.state.model_name or not self.state.messages:
            log.add_system("Nothing to save.")
            return
        saved = finalize_session(
            self.state.model_name, self.state.messages,
            self.temperature, self.state.start_time,
        )
        log.add_system(f"Saved: {saved}" if saved else "Nothing user-authored to save.")

    def action_toggle_tools(self) -> None:
        self.tools_enabled = not self.tools_enabled
        self.query_one(ChatLog).add_system(
            f"Tools {'enabled' if self.tools_enabled else 'disabled'}."
        )

    # ── Agent mode ────────────────────────────────────────────────────────

    def action_agent(self) -> None:
        log = self.query_one(ChatLog)
        if self.state.mode == "agent":
            self._exit_agent()
            return
        if self.current_model in ("(no model)", "", None):
            log.add_system("Select a model first (Ctrl+O).")
            return
        ok, reason, max_ctx = agent_capable(self.current_model, self.state.backend)
        if not ok:
            log.add_system(
                f"[#ff6e6e]Agent mode needs a tool-capable model:[/#ff6e6e] {reason}. "
                "Pick another model (Ctrl+O)."
            )
            return
        # Enter agent mode — raise context, swap to the agent system prompt.
        self.state.mode = "agent"
        self.state.agent_submode = "build"
        target_ctx = max(config.agent_min_context,
                         min(max_ctx or config.agent_default_context,
                             config.agent_default_context))
        self.context_length = target_ctx
        self.state.context_length = target_ctx
        self._apply_agent_prompt()
        self._sync_status(agent_mode=True, agent_submode="build")
        log.add_system(
            f"[#a855f7]◆ Agent mode — build[/#a855f7]  "
            f"[#6b6b73]ctx {target_ctx} · F2 plan/build · Ctrl+G exit[/#6b6b73]"
        )

    def _exit_agent(self) -> None:
        self.state.mode = "chat"
        # Restore the normal chat system prompt.
        from ..memory import build_system_prompt
        sp = build_system_prompt()
        if self.state.messages and self.state.messages[0].get("role") == "system":
            self.state.messages[0]["content"] = sp
        self._sync_status(agent_mode=False)
        self.query_one(ChatLog).add_system("Left agent mode — back to chat.")

    def action_toggle_agent_submode(self) -> None:
        if self.state.mode != "agent":
            return
        self.state.agent_submode = "plan" if self.state.agent_submode == "build" else "build"
        self._apply_agent_prompt()
        self._sync_status(agent_submode=self.state.agent_submode)
        sub = self.state.agent_submode
        note = ("read-only; edits/commands need approval" if sub == "plan"
                else "full access")
        self.query_one(ChatLog).add_system(
            f"[#a855f7]◆ Agent · {sub}[/#a855f7]  [#6b6b73]{note}[/#6b6b73]"
        )

    def _apply_agent_prompt(self) -> None:
        sp = agent_system_prompt(self.state.agent_submode)
        msgs = self.state.messages
        if msgs and msgs[0].get("role") == "system":
            msgs[0]["content"] = sp
        else:
            msgs.insert(0, {"role": "system", "content": sp})

    def _make_approve_fn(self):
        """Build a blocking approve(name, args)->bool for the worker thread.

        Read-only tools (and Build mode) auto-allow. In Plan mode, mutating
        tools pop a PermissionModal on the UI thread; the worker blocks on an
        Event until the user decides.
        """
        import threading
        submode = self.state.agent_submode

        def approve(name: str, args: dict) -> bool:
            if permission_for(submode, name) != "ask":
                return True
            ev = threading.Event()
            box = {"ok": False}

            def ask():
                def after(allowed):
                    box["ok"] = bool(allowed)
                    ev.set()
                self.app.push_screen(PermissionModal(name, args), after)

            try:
                self.app.call_from_thread(ask)
            except Exception:
                return False
            ev.wait()
            return box["ok"]

        return approve

    def action_cancel_stream(self) -> None:
        # Cancel the chat-stream worker group. Sync workers can't be
        # interrupted mid-iteration — they'll finish the current HTTP read
        # and exit. The _cancelled flag suppresses any late events that
        # arrive before Done.
        if self.streaming:
            self._cancelled = True
            try:
                self.workers.cancel_group(self, "chat-stream")
            except Exception:
                pass
            self.query_one(ChatLog).end_assistant()
            self.query_one(ChatLog).add_system("Stream cancelled.")
            self.streaming = False

    def action_quit(self) -> None:
        if self.state.model_name and self.state.messages:
            try:
                finalize_session(
                    self.state.model_name, self.state.messages,
                    self.temperature, self.state.start_time,
                    backend=self.state.backend, stream_model=self.state.stream_model,
                )
            except Exception:
                pass
        # Unload happens in on_unmount (covers every exit path, not just Ctrl+Q).
        self.app.exit()

    def _unload_current_model(self) -> None:
        """Free VRAM/RAM by unloading the active model. Only Ollama supports
        unload — llama.cpp owns its own process and API models hold nothing
        locally."""
        if self.state.backend == "ollama" and self.state.model_name:
            try:
                unload_model(self.state.model_name)
            except Exception:
                pass

    def on_unmount(self) -> None:
        # Fires on every shutdown (Ctrl+Q, Ctrl+C, SIGTERM, window close), so
        # the model is always released even when action_quit is bypassed.
        self._unload_current_model()

    # ── Cancellation message ─────────────────────────────────────────────

    def on_stream_cancel_requested(self, _msg: StreamCancelRequested) -> None:
        self.action_cancel_stream()
