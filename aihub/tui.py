"""
AIHub TUI Edition — Obsidian Neon (v0.1.4)
Split-pane layout: persistent sidebar + dynamic content panes.
Color scheme: dark graphite + cyan/lime neon accents.
"""
import json
import os
import psutil
from datetime import datetime
from typing import Optional, List, Dict, Any

from textual.app import App, ComposeResult
from textual.screen import Screen, ModalScreen
from textual.widgets import (
    ListView, ListItem, Label, Input, Button,
    Static, TextArea, ContentSwitcher,
)
from textual.containers import Vertical, Horizontal, ScrollableContainer
from textual.binding import Binding
from textual.reactive import reactive
from textual import work
from textual.message import Message

from .config import config, HISTORY_DIR
from .ollama_client import (
    get_local_model_sizes, get_model_info, chat_stream,
    is_ollama_running, unload_model,
)
from .cli import load_registry_models
from .hardware import get_available_ram_gb, estimate_kv_cache_gb
from .memory import (
    load_memory, save_memory,
    update_memory_entry, clear_memory, build_system_prompt,
)
from .history import list_sessions, load_session as load_chat_session, save_session
from .models import get_capability_badges, get_speed_label, sort_models_for_hardware


# ─── CSS ─────────────────────────────────────────────────────────────────────

APP_CSS = """
Screen {
    background: #0d0f17;
    color: #e2e8f0;
}

/* ── Layout ── */
#body {
    height: 1fr;
    width: 100%;
}

#sidebar {
    width: 26;
    height: 100%;
    background: #0a0c14;
    border-right: solid #1e2235;
}

#sidebar-logo {
    height: 4;
    background: #0a0c14;
    border-bottom: solid #1e2235;
    color: #00e5cc;
    text-style: bold;
    content-align: center middle;
    padding: 0 1;
}

#sidebar-nav {
    height: 1fr;
    background: #0a0c14;
    border: none;
    padding: 0;
}

#sidebar-nav > ListItem {
    height: 3;
    padding: 0 2;
    background: #0a0c14;
    border: none;
    border-left: thick #0a0c14;
    color: #4a5568;
}

#sidebar-nav > ListItem:hover {
    background: #141728;
    color: #94a3b8;
    border-left: thick #2d3a5e;
}

#sidebar-nav > ListItem.--highlight {
    background: #0a1a18;
    color: #00e5cc;
    border-left: thick #00e5cc;
    text-style: bold;
}

#sidebar-nav > ListItem.active {
    background: #0a1a18;
    color: #00e5cc;
    border-left: thick #00e5cc;
    text-style: bold;
}

#sidebar-version {
    height: 2;
    background: #0a0c14;
    border-top: solid #1e2235;
    color: #2d3a5e;
    content-align: center middle;
}

#main-area {
    width: 1fr;
    height: 100%;
    background: #0d0f17;
}

ContentSwitcher {
    width: 100%;
    height: 100%;
}

/* ── Status bar ── */
#status-bar {
    dock: bottom;
    height: 1;
    background: #0a0c14;
    border-top: solid #1e2235;
    padding: 0 2;
    color: #4a5568;
}

/* ── Welcome pane ── */
#pane-welcome {
    align: center middle;
    background: #0d0f17;
}

#welcome-logo {
    width: 52;
    height: 6;
    content-align: center middle;
    color: #00e5cc;
    text-style: bold;
    border: solid #1e2235;
    background: #0e1020;
    padding: 1 2;
}

#welcome-subtitle {
    width: 52;
    content-align: center middle;
    color: #4a5568;
    margin-top: 1;
}

#welcome-status {
    width: 52;
    content-align: center middle;
    margin-top: 1;
}

/* ── Model browser ── */
#pane-models {
    background: #0d0f17;
}

#models-search-row {
    height: 3;
    padding: 0 1;
    background: #0a0c14;
    border-bottom: solid #1e2235;
}

#model-search-input {
    width: 1fr;
    background: #13151f;
    border: solid #1e2235;
    color: #e2e8f0;
}

#models-filter-row {
    height: 3;
    padding: 0 1;
    background: #0a0c14;
    border-bottom: solid #1e2235;
}

.filter-btn {
    height: 1;
    min-width: 13;
    margin-right: 1;
    background: #13151f;
    border: solid #1e2235;
    color: #4a5568;
}

.filter-btn.active-filter {
    background: #0a1a18;
    color: #00e5cc;
    border: solid #00e5cc;
}

#hw-bar {
    height: 1;
    background: #0a0c14;
    padding: 0 2;
    border-bottom: solid #1e2235;
    color: #4a5568;
}

#model-list-view {
    height: 1fr;
    background: #0d0f17;
}

#model-list-view > ListItem {
    height: 5;
    padding: 0 1;
    border-bottom: solid #13151f;
    background: #0d0f17;
}

#model-list-view > ListItem:hover {
    background: #111520;
}

#model-list-view > ListItem.--highlight {
    background: #111520;
}

#model-list-view > ListItem.installed {
    border-left: thick #00e5cc;
}

#model-list-view > ListItem.incompatible {
    opacity: 0.4;
}

/* ── Chat pane ── */
#pane-chat {
    background: #0d0f17;
}

#chat-header-bar {
    height: 2;
    background: #0a0c14;
    border-bottom: solid #1e2235;
    padding: 0 2;
    color: #4a5568;
    content-align: left middle;
}

#chat-messages {
    height: 1fr;
    background: #0d0f17;
    padding: 1 2;
}

.msg-user {
    background: #0d1a2e;
    border-left: thick #00e5cc;
    padding: 0 1;
    margin-bottom: 1;
    color: #93c5fd;
}

.msg-ai {
    background: #111520;
    border-left: thick #b8ff57;
    padding: 0 1;
    margin-bottom: 1;
    color: #d1fae5;
}

.msg-tool {
    background: #0a160f;
    border-left: thick #00cc66;
    padding: 0 1;
    margin-bottom: 1;
    color: #6ee7b7;
}

.msg-system {
    background: #0f0f17;
    border-left: thick #2d3a5e;
    padding: 0 1;
    margin-bottom: 1;
    color: #64748b;
}

#chat-input-row {
    height: 3;
    background: #0a0c14;
    border-top: solid #1e2235;
    padding: 0 1;
}

#chat-input-field {
    width: 1fr;
    background: #13151f;
    border: solid #1e2235;
    color: #e2e8f0;
}

#chat-send-btn {
    width: 10;
    background: #00e5cc;
    color: #0a0c14;
    border: none;
    text-style: bold;
}

#chat-send-btn:hover {
    background: #00b89c;
}

/* ── History pane ── */
#pane-history {
    background: #0d0f17;
}

#history-header {
    height: 2;
    background: #0a0c14;
    border-bottom: solid #1e2235;
    padding: 0 2;
    content-align: left middle;
}

#history-models-list {
    height: 1fr;
    background: #0d0f17;
}

/* ── Memory pane ── */
#pane-memory {
    background: #0d0f17;
}

#memory-toolbar {
    height: 3;
    background: #0a0c14;
    border-bottom: solid #1e2235;
    padding: 0 2;
}

#memory-toolbar Static {
    width: 1fr;
    content-align: left middle;
}

#memory-editor {
    height: 1fr;
}

/* ── Hardware pane ── */
#pane-hardware {
    padding: 2;
    background: #0d0f17;
}

#hw-title {
    height: 2;
    color: #00e5cc;
    text-style: bold;
}

#hw-content {
    height: 1fr;
    padding: 1 0;
}

/* ── Config pane ── */
#pane-config {
    padding: 2;
    background: #0d0f17;
}

#config-title {
    height: 2;
    color: #00e5cc;
    text-style: bold;
}

/* ── History session screen ── */
_HistorySessionScreen {
    background: #0d0f17;
}

#sessions-header {
    height: 2;
    background: #0a0c14;
    border-bottom: solid #1e2235;
    padding: 0 2;
    content-align: left middle;
}

#sessions-lv {
    height: 1fr;
}

/* ── Context modal ── */
ContextConfigModal {
    align: center middle;
}

#ctx-modal-box {
    width: 55;
    height: auto;
    background: #0e1020;
    border: solid #00e5cc;
    padding: 2;
}

#ctx-modal-box Label {
    margin-bottom: 1;
}

#ctx-modal-actions {
    margin-top: 2;
    height: 3;
}

#ctx-start-btn {
    width: 14;
    background: #00e5cc;
    color: #0a0c14;
    border: none;
    text-style: bold;
    margin-right: 1;
}

#ctx-cancel-btn {
    width: 10;
    background: #1e2235;
    color: #94a3b8;
    border: none;
}
"""

# ─── Category filter options ──────────────────────────────────────────────────

CAT_OPTIONS = [
    ("★ Rec",   "recommended"),
    ("All",     "all"),
    ("Small",   "small"),
    ("Medium",  "medium"),
    ("Large",   "large"),
    ("XLarge",  "xlarge"),
]

LOGO = "◈  A I H U B  T U I"

# ─── Inter-widget messages ────────────────────────────────────────────────────

class RequestStartChat(Message):
    def __init__(self, model_name: str, context_length: int) -> None:
        super().__init__()
        self.model_name = model_name
        self.context_length = context_length


class RequestLoadSession(Message):
    def __init__(self, model_name: str, messages: List[Dict]) -> None:
        super().__init__()
        self.model_name = model_name
        self.messages = messages


# ─── Model card (list item) ───────────────────────────────────────────────────

class ModelCard(ListItem):
    def __init__(self, model_data: dict, installed: bool,
                 hw_compatible: bool, ctx_str: str = "?", **kwargs):
        super().__init__(**kwargs)
        self.model_data = model_data
        self.installed = installed
        self.hw_compatible = hw_compatible
        self.ctx_str = ctx_str
        if installed:
            self.add_class("installed")
        elif not hw_compatible and not model_data.get("url", "").startswith("api://"):
            self.add_class("incompatible")

    def compose(self) -> ComposeResult:
        m = self.model_data
        name = m.get("name", "Unknown")
        vram = m.get("vram_required", 0)
        size_gb = m.get("size_gb", vram)
        is_api = m.get("url", "").startswith("api://")
        speed = get_speed_label(m)
        badges = get_capability_badges(m, max_badges=3)
        use_case = ", ".join(m.get("use_cases", [])[:2])

        if self.installed:
            status = "[bold #00e5cc]✓ INSTALLED[/bold #00e5cc]"
            name_mk = f"[bold #e2e8f0]{name}[/bold #e2e8f0]"
        elif not self.hw_compatible and not is_api:
            status = "[#ff4d6d]⚠ EXCEEDS HW[/#ff4d6d]"
            name_mk = f"[#4a5568]{name}[/#4a5568]"
        else:
            status = "[#64748b]⬡ AVAILABLE[/#64748b]"
            name_mk = f"[#94a3b8]{name}[/#94a3b8]"

        ram_str = "API" if is_api else f"{vram}GB"
        size_str = "" if is_api else f" · {size_gb:.1f}GB"
        badge_str = (
            "  ".join(f"[#b8ff57]{b}[/#b8ff57]" for b in badges)
            if badges else f"[#4a5568]{use_case}[/#4a5568]"
        )

        yield Vertical(
            Horizontal(
                Label(name_mk),
                Label(f"  {status}"),
            ),
            Label(f"[#4a5568]{ram_str}{size_str} · {speed} · ctx:{self.ctx_str}[/#4a5568]"),
            Label(badge_str),
        )


# ─── Context config modal ─────────────────────────────────────────────────────

class ContextConfigModal(ModalScreen):
    def __init__(self, model_name: str, **kwargs):
        super().__init__(**kwargs)
        self.model_name = model_name
        self._default = config.default_context_length

    def compose(self) -> ComposeResult:
        est = estimate_kv_cache_gb(self._default, self.model_name)
        yield Vertical(
            Label(f"[bold #00e5cc]◈ Chat: {self.model_name}[/bold #00e5cc]"),
            Label("[#64748b]Context window (tokens):[/#64748b]"),
            Input(value=str(self._default), id="ctx-input"),
            Label(
                f"[#64748b]KV cache ≈ [bold #b8ff57]{est} GB[/bold #b8ff57][/#64748b]",
                id="ctx-est",
            ),
            Horizontal(
                Button("▶ Start Chat", id="ctx-start-btn"),
                Button("Cancel", id="ctx-cancel-btn"),
                id="ctx-modal-actions",
            ),
            id="ctx-modal-box",
        )

    def on_input_changed(self, event: Input.Changed) -> None:
        try:
            val = int(event.value)
            est = estimate_kv_cache_gb(val, self.model_name)
            self.query_one("#ctx-est", Label).update(
                f"[#64748b]KV cache ≈ [bold #b8ff57]{est} GB[/bold #b8ff57][/#64748b]"
            )
        except (ValueError, TypeError):
            pass

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "ctx-start-btn":
            try:
                ctx = int(self.query_one("#ctx-input", Input).value)
            except (ValueError, TypeError):
                ctx = self._default
            self.dismiss(ctx)
        else:
            self.dismiss(None)


# ─── Model browser pane ───────────────────────────────────────────────────────

class ModelBrowserPane(Vertical):
    _active_cat: str = "recommended"

    def compose(self) -> ComposeResult:
        yield Horizontal(
            Input(placeholder="  Search models…", id="model-search-input"),
            Button("↺", id="models-refresh-btn"),
            id="models-search-row",
        )
        yield Horizontal(
            *[Button(lbl, id=f"filter-{val}", classes="filter-btn") for lbl, val in CAT_OPTIONS],
            id="models-filter-row",
        )
        yield Static("", id="hw-bar")
        yield ListView(id="model-list-view")

    def on_mount(self) -> None:
        self._set_filter("recommended")
        self.refresh_models()

    def _set_filter(self, cat: str) -> None:
        self._active_cat = cat
        for _, val in CAT_OPTIONS:
            try:
                btn = self.query_one(f"#filter-{val}", Button)
                if val == cat:
                    btn.add_class("active-filter")
                else:
                    btn.remove_class("active-filter")
            except Exception:
                pass

    def refresh_models(self) -> None:
        lv = self.query_one("#model-list-view", ListView)
        lv.clear()

        hw_ram = get_available_ram_gb()
        registry = load_registry_models()
        local_sizes = get_local_model_sizes()
        local_names = set(local_sizes.keys())

        ollama_ok = is_ollama_running()
        ollama_str = "[#00e5cc]● running[/#00e5cc]" if ollama_ok else "[#ff4d6d]○ offline[/#ff4d6d]"
        self.query_one("#hw-bar", Static).update(
            f"  [#64748b]HW limit:[/#64748b] [bold #00e5cc]{hw_ram:.1f}GB[/bold #00e5cc]  ·  "
            f"[#64748b]installed:[/#64748b] [#b8ff57]{len(local_names)}[/#b8ff57]  ·  "
            f"Ollama {ollama_str}"
        )

        cat_ranges = {
            "small": (0, 4), "medium": (4, 8),
            "large": (8, 16), "xlarge": (16, 99999),
        }
        if self._active_cat == "recommended":
            registry = [
                m for m in registry
                if m.get("vram_required", 0) <= hw_ram or m.get("vram_required", 0) == 0
            ]
        elif self._active_cat in cat_ranges:
            cmin, cmax = cat_ranges[self._active_cat]
            registry = [
                m for m in registry
                if cmin < m.get("vram_required", 0) <= cmax
                or (self._active_cat == "small" and m.get("vram_required", 0) == 0)
            ]

        term = self.query_one("#model-search-input", Input).value.lower().strip()
        if term:
            registry = [
                m for m in registry
                if term in m.get("name", "").lower()
                or any(term in c.lower() for c in m.get("capabilities", []))
                or any(term in t.lower() for t in m.get("tags", []))
                or any(term in u.lower() for u in m.get("use_cases", []))
            ]

        installed = [m for m in registry if m["name"] in local_names]
        not_inst = [m for m in registry if m["name"] not in local_names]
        compatible, incompatible = sort_models_for_hardware(not_inst, hw_ram)

        def _add(m: dict, inst: bool, compat: bool) -> None:
            ctx_str = "?"
            if inst:
                try:
                    info = get_model_info(m["name"])
                    ctx_raw = info.get("context_length", 0)
                    ctx_str = f"{int(ctx_raw) // 1024}k" if ctx_raw else "?"
                except Exception:
                    pass
            lv.append(ModelCard(m, inst, compat, ctx_str))

        for m in sorted(installed, key=lambda x: x.get("vram_required", 0), reverse=True):
            _add(m, True, True)
        for m in compatible:
            _add(m, False, True)
        for m in incompatible:
            _add(m, False, False)

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "model-search-input":
            self.refresh_models()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        btn_id = event.button.id or ""
        if btn_id == "models-refresh-btn":
            self.refresh_models()
            return
        for _, val in CAT_OPTIONS:
            if btn_id == f"filter-{val}":
                self._set_filter(val)
                self.refresh_models()
                return

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        item = event.item
        if not isinstance(item, ModelCard):
            return
        model_name = item.model_data["name"]
        if item.installed:
            def _on_ctx(ctx: Optional[int]) -> None:
                if ctx is not None:
                    self.post_message(RequestStartChat(model_name, ctx))
            self.app.push_screen(ContextConfigModal(model_name), _on_ctx)
        else:
            self.app.notify(
                f"Run: aihub models-download {model_name}",
                title="Not installed",
                severity="warning",
            )


# ─── Chat pane ────────────────────────────────────────────────────────────────

class ChatPane(Vertical):
    current_model: reactive[Optional[str]] = reactive(None)

    def compose(self) -> ComposeResult:
        yield Static(
            "  [#4a5568]No model selected — browse Models (F1) to start a chat[/#4a5568]",
            id="chat-header-bar",
        )
        yield ScrollableContainer(id="chat-messages")
        yield Horizontal(
            Input(placeholder="  Message… (/help for commands)", id="chat-input-field"),
            Button("Send ›", id="chat-send-btn"),
            id="chat-input-row",
        )

    def start_chat(
        self,
        model_name: str,
        context_length: int,
        messages: Optional[List[Dict]] = None,
    ) -> None:
        self.current_model = model_name
        self.context_length = context_length
        self._start_time = datetime.now()
        self.messages: List[Dict[str, Any]] = []

        if messages:
            self.messages = list(messages)
        else:
            sys_prompt = build_system_prompt(model_name)
            if sys_prompt:
                self.messages.append({"role": "system", "content": sys_prompt})

        kv_gb = estimate_kv_cache_gb(context_length, model_name)
        has_mem = bool(build_system_prompt(model_name))
        mem_str = "[#b8ff57]📝 memory[/#b8ff57]" if has_mem else "[#4a5568]no memory[/#4a5568]"
        self.query_one("#chat-header-bar", Static).update(
            f"  [bold #00e5cc]{model_name}[/bold #00e5cc]  ·  "
            f"[#4a5568]ctx:[/#4a5568][#b8ff57]{context_length // 1024}k[/#b8ff57]"
            f"[#4a5568] (+{kv_gb}GB)  ·  [/#4a5568]{mem_str}"
            f"[#4a5568]  ·  /help for commands[/#4a5568]"
        )

        display = self.query_one("#chat-messages", ScrollableContainer)
        display.query(Static).remove()

        if messages:
            for msg in self.messages:
                role = msg.get("role", "")
                content = msg.get("content", "")
                if content and role not in ("system", "tool"):
                    self._add_bubble(role, content)

    def _add_bubble(self, role: str, content: str) -> None:
        display = self.query_one("#chat-messages", ScrollableContainer)
        css_cls = {"user": "msg-user", "assistant": "msg-ai", "tool": "msg-tool"}.get(
            role, "msg-system"
        )
        prefix = {
            "user": "[bold #00e5cc]You ›[/bold #00e5cc] ",
            "assistant": "[bold #b8ff57]AI  ›[/bold #b8ff57] ",
            "tool": "[bold #00cc66]⚡[/bold #00cc66] ",
        }.get(role, "[#4a5568]ℹ[/#4a5568] ")
        widget = Static(f"{prefix}{content}", classes=css_cls)
        display.mount(widget)
        display.scroll_end(animate=False)

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "chat-input-field":
            await self._send(event.value)
            event.input.value = ""

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "chat-send-btn":
            inp = self.query_one("#chat-input-field", Input)
            await self._send(inp.value)
            inp.value = ""

    async def _send(self, text: str) -> None:
        text = text.strip()
        if not text:
            return
        if not self.current_model:
            self.app.notify("Select a model from Models (F1) first.", severity="warning")
            return
        if text.startswith("/"):
            self._slash(text)
            return
        self.messages.append({"role": "user", "content": text})
        self._add_bubble("user", text)
        if not is_ollama_running():
            self._add_bubble("assistant", "[#ff4d6d]Ollama is not running — start with: ollama serve[/#ff4d6d]")
            return
        self._stream()

    def _slash(self, cmd: str) -> None:
        parts = cmd.split(maxsplit=2)
        c = parts[0].lower()
        if c == "/help":
            self._add_bubble("system",
                "/clear  /memory  /memory save <k> <v>  /memory clear  "
                "/memoryadd [chat|global]  exit")
        elif c == "/clear":
            sys_msgs = [m for m in self.messages if m.get("role") == "system"]
            self.messages = sys_msgs
            self.query_one("#chat-messages", ScrollableContainer).query(Static).remove()
            self._add_bubble("system", "Context cleared.")
        elif c == "/memory":
            sub = parts[1].lower() if len(parts) > 1 else ""
            if sub == "save" and len(parts) == 3:
                kv = parts[2].split(maxsplit=1)
                if len(kv) == 2:
                    update_memory_entry(self.current_model, kv[0], kv[1])
                    self._add_bubble("system", f"Saved: {kv[0]} → {kv[1]}")
            elif sub == "clear":
                clear_memory(self.current_model)
                self._add_bubble("system", "Memory cleared.")
            else:
                mem = load_memory(self.current_model)
                self._add_bubble("system", mem if mem else "No memory stored.")
        elif c == "/memoryadd":
            target = parts[1].lower() if len(parts) > 1 else "chat"
            if target in ("chat", "global"):
                self._extract_memory(target)
            else:
                self._add_bubble("system", "Usage: /memoryadd [chat|global]")
        else:
            self._add_bubble("system", f"Unknown command: {c}. Type /help.")

    @work(thread=True, exclusive=True)
    def _extract_memory(self, target: str) -> None:
        from .memory import extract_and_update_memory
        self.app.call_from_thread(self._add_bubble, "system", f"Extracting ({target})…")
        try:
            result = extract_and_update_memory(self.current_model, self.messages, target=target)
            if result.startswith("Error:"):
                self.app.call_from_thread(self._add_bubble, "system", f"[#ff4d6d]{result}[/#ff4d6d]")
            else:
                self.app.call_from_thread(
                    self._add_bubble, "system",
                    f"[#b8ff57]Memory updated ({target}):[/#b8ff57]\n{result}"
                )
        except Exception as exc:
            self.app.call_from_thread(self._add_bubble, "system", f"Error: {exc}")

    @work(thread=True, exclusive=True)
    def _stream(self) -> None:
        from .tools import run_tool, TOOLS_SCHEMA
        tools_avail = config.tools_enabled
        max_rounds = 15

        for _ in range(max_rounds):
            full = ""
            tool_calls: List[Dict] = []

            def _mount_ai() -> Static:
                display = self.query_one("#chat-messages", ScrollableContainer)
                w = Static("[bold #b8ff57]AI  ›[/bold #b8ff57] ", classes="msg-ai")
                display.mount(w)
                display.scroll_end(animate=False)
                return w

            ai_widget = self.app.call_from_thread(_mount_ai)

            try:
                kwargs: Dict[str, Any] = {"options": {"num_ctx": self.context_length}}
                if tools_avail:
                    kwargs["tools"] = TOOLS_SCHEMA

                def _iter_chunks() -> None:
                    nonlocal full, tool_calls, kwargs
                    try:
                        for chunk in chat_stream(self.current_model, self.messages, 0.7, **kwargs):
                            if "error" in chunk:
                                err = str(chunk["error"])
                                if "does not support tools" in err and "tools" in kwargs:
                                    kwargs.pop("tools")
                                    return _iter_chunks()
                                self.app.call_from_thread(
                                    self._add_bubble, "assistant",
                                    f"[#ff4d6d]Error: {err}[/#ff4d6d]"
                                )
                                return
                            msg = chunk.get("message", {})
                            piece = msg.get("content", "")
                            if piece:
                                full += piece
                                self.app.call_from_thread(
                                    ai_widget.update,
                                    f"[bold #b8ff57]AI  ›[/bold #b8ff57] {full}"
                                )
                            for tc in msg.get("tool_calls", []):
                                tool_calls.append(tc)
                    except Exception as exc:
                        if "does not support tools" in str(exc) and "tools" in kwargs:
                            kwargs.pop("tools")
                            return _iter_chunks()
                        raise

                _iter_chunks()

                def _scroll():
                    try:
                        self.query_one("#chat-messages", ScrollableContainer).scroll_end(animate=False)
                    except Exception:
                        pass
                self.app.call_from_thread(_scroll)

            except Exception as exc:
                self.app.call_from_thread(self._add_bubble, "assistant", f"[#ff4d6d]Error: {exc}[/#ff4d6d]")
                return

            if not tool_calls:
                self.messages.append({"role": "assistant", "content": full})
                return

            self.messages.append({"role": "assistant", "content": full, "tool_calls": tool_calls})

            for tc in tool_calls:
                fn = tc.get("function", {})
                name = fn.get("name", "")
                args = fn.get("arguments", {})
                if isinstance(args, str):
                    try:
                        args = json.loads(args)
                    except Exception:
                        args = {}
                self.app.call_from_thread(
                    self._add_bubble, "tool", f"⚡ {name}({json.dumps(args)[:80]}…)"
                )
                result = run_tool(name, **args)
                self.app.call_from_thread(self._add_bubble, "tool", result[:400])
                self.messages.append({"role": "tool", "content": result})

        self.app.call_from_thread(
            self._add_bubble, "system", "[#ff4d6d]Tool call loop limit reached.[/#ff4d6d]"
        )

    def save_if_needed(self) -> None:
        if hasattr(self, "messages") and self.current_model:
            user_msgs = [m for m in self.messages if m.get("role") == "user"]
            if user_msgs:
                save_session(self.current_model, self.messages, 0.7,
                             getattr(self, "_start_time", datetime.now()))


# ─── History pane ─────────────────────────────────────────────────────────────

class HistoryPane(Vertical):
    def compose(self) -> ComposeResult:
        yield Static(
            "  [bold #00e5cc]◷ History[/bold #00e5cc]  [#4a5568]— select a model[/#4a5568]",
            id="history-header",
        )
        yield ListView(id="history-models-list")

    def on_mount(self) -> None:
        lv = self.query_one("#history-models-list", ListView)
        if not os.path.exists(HISTORY_DIR):
            lv.append(ListItem(Label("[#4a5568]  No history yet.[/#4a5568]")))
            return
        for d in sorted(os.listdir(HISTORY_DIR)):
            if os.path.isdir(os.path.join(HISTORY_DIR, d)):
                lv.append(ListItem(Label(f"  [#94a3b8]{d}[/#94a3b8]"), id=f"hm-{d}"))

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        item = event.item
        if item and item.id and item.id.startswith("hm-"):
            model_name = item.id[3:]

            def _callback(result: Optional[Dict]) -> None:
                if result:
                    self.post_message(RequestLoadSession(result["model"], result["messages"]))

            self.app.push_screen(_HistorySessionScreen(model_name), _callback)


class _HistorySessionScreen(ModalScreen):
    BINDINGS = [Binding("escape", "dismiss_none", "Back")]

    def __init__(self, model_name: str, **kwargs):
        super().__init__(**kwargs)
        self.model_name = model_name
        self._sessions: List[Dict] = []

    def compose(self) -> ComposeResult:
        yield Vertical(
            Static(
                f"  [bold #00e5cc]◷ {self.model_name}[/bold #00e5cc]"
                f"  [#4a5568](ESC to go back)[/#4a5568]",
                id="sessions-header",
            ),
            ListView(id="sessions-lv"),
        )

    def on_mount(self) -> None:
        lv = self.query_one("#sessions-lv", ListView)
        self._sessions = list_sessions(self.model_name)
        for i, s in enumerate(self._sessions[:30]):
            ts = s["start_time"][:19].replace("T", " ")
            lv.append(
                ListItem(
                    Label(f"  [#94a3b8]{ts}[/#94a3b8]  [#4a5568]({s['message_count']} msgs)[/#4a5568]"),
                    id=f"sess-{i}",
                )
            )

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        item = event.item
        if item and item.id and item.id.startswith("sess-"):
            idx = int(item.id[5:])
            if 0 <= idx < len(self._sessions):
                msgs = load_chat_session(self.model_name, self._sessions[idx]["filename"])
                if msgs:
                    self.dismiss({"model": self.model_name, "messages": msgs})
                    return
        self.dismiss(None)

    def action_dismiss_none(self) -> None:
        self.dismiss(None)


# ─── Memory pane ──────────────────────────────────────────────────────────────

class MemoryPane(Vertical):
    BINDINGS = [Binding("ctrl+s", "save_mem", "Save")]

    def compose(self) -> ComposeResult:
        yield Horizontal(
            Static("  [bold #00e5cc]◉ Global Memory[/bold #00e5cc]"),
            Button("Save  Ctrl+S", id="memory-save-btn"),
            id="memory-toolbar",
        )
        yield TextArea(id="memory-editor", show_line_numbers=True)

    def on_mount(self) -> None:
        editor = self.query_one("#memory-editor", TextArea)
        mem = load_memory("global")
        editor.load_text(mem if mem else "## Global Memory\n\nAdd facts here.\n")

    def action_save_mem(self) -> None:
        editor = self.query_one("#memory-editor", TextArea)
        save_memory("global", editor.text)
        self.app.notify("Global memory saved.", title="Memory")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "memory-save-btn":
            self.action_save_mem()


# ─── Hardware pane ────────────────────────────────────────────────────────────

class HardwarePane(Vertical):
    def compose(self) -> ComposeResult:
        yield Static("  [bold #00e5cc]◬ Hardware Diagnostics[/bold #00e5cc]", id="hw-title")
        yield Static("", id="hw-content")
        yield Button("↺ Refresh", id="hw-refresh-btn")

    def on_mount(self) -> None:
        self._refresh()

    def _refresh(self) -> None:
        try:
            ram = psutil.virtual_memory()
            cpu = psutil.cpu_percent(interval=0.2)
            disk = psutil.disk_usage("/")
            avail = get_available_ram_gb()

            lines = [
                f"  [bold #00e5cc]CPU[/bold #00e5cc]   usage:  [#b8ff57]{cpu:.1f}%[/#b8ff57]",
                f"  [bold #00e5cc]RAM[/bold #00e5cc]   total:  [#b8ff57]{ram.total / 1e9:.1f} GB[/#b8ff57]"
                f"   used: [#b8ff57]{ram.used / 1e9:.1f} GB[/#b8ff57]"
                f"   available: [bold #00e5cc]{avail:.1f} GB[/bold #00e5cc]",
                f"  [bold #00e5cc]DISK[/bold #00e5cc]  total:  [#b8ff57]{disk.total / 1e9:.0f} GB[/#b8ff57]"
                f"   free: [#b8ff57]{disk.free / 1e9:.1f} GB[/#b8ff57]",
                "",
                f"  [#4a5568]For GPU details run: [bold]aihub hardware-scan[/bold] in terminal[/#4a5568]",
            ]
            self.query_one("#hw-content", Static).update("\n".join(lines))
        except Exception as exc:
            self.query_one("#hw-content", Static).update(f"  [#ff4d6d]{exc}[/#ff4d6d]")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "hw-refresh-btn":
            self._refresh()


# ─── Config pane ──────────────────────────────────────────────────────────────

class ConfigPane(Vertical):
    def compose(self) -> ComposeResult:
        yield Static("  [bold #00e5cc]◇ Configuration[/bold #00e5cc]", id="config-title")
        yield Static("", id="config-content")

    def on_mount(self) -> None:
        cfg_path = os.path.expanduser("~/.aihub/config.yaml")
        if os.path.exists(cfg_path):
            try:
                with open(cfg_path) as f:
                    raw = f.read()
                self.query_one("#config-content", Static).update(
                    f"  [#4a5568]{cfg_path}[/#4a5568]\n\n  [#94a3b8]{raw}[/#94a3b8]"
                )
            except Exception as exc:
                self.query_one("#config-content", Static).update(f"  [#ff4d6d]{exc}[/#ff4d6d]")
        else:
            self.query_one("#config-content", Static).update(
                "  [#4a5568]No config file found at ~/.aihub/config.yaml[/#4a5568]"
            )


# ─── Welcome pane ─────────────────────────────────────────────────────────────

class WelcomePane(Vertical):
    def compose(self) -> ComposeResult:
        yield Static(
            "  ╔═╗  ╦╦  ╦ ╦  ╔╗\n"
            "  ╠═╣  ║╠═╣ ║  ║  ╠╩╗\n"
            "  ╩ ╩  ╩╩ ╩ ╚═╝  ╚═╝  TUI",
            id="welcome-logo",
        )
        yield Static(
            "  [#4a5568]hardware-aware local AI · ollama backend · memory · agentic tools[/#4a5568]",
            id="welcome-subtitle",
        )
        yield Static("", id="welcome-status")

    def on_mount(self) -> None:
        ollama_ok = is_ollama_running()
        try:
            local_sizes = get_local_model_sizes()
            n_models = len(local_sizes)
        except Exception:
            n_models = 0
        avail = get_available_ram_gb()

        if ollama_ok:
            status = (
                f"  [#00e5cc]● Ollama running[/#00e5cc]  ·  "
                f"[#b8ff57]{n_models} models[/#b8ff57]  ·  "
                f"[#4a5568]{avail:.1f} GB RAM available[/#4a5568]"
            )
        else:
            status = (
                "  [#ff4d6d]○ Ollama not running[/#ff4d6d]  —  "
                "[#4a5568]start with: [bold]ollama serve[/bold][/#4a5568]"
            )
        self.query_one("#welcome-status", Static).update(status)


# ─── Navigation map ───────────────────────────────────────────────────────────

NAV = [
    ("F1  ⬡  Models",   "pane-models"),
    ("F2  ◈  Chat",     "pane-chat"),
    ("F3  ◷  History",  "pane-history"),
    ("F4  ◉  Memory",   "pane-memory"),
    ("F5  ◬  Hardware", "pane-hardware"),
    ("F6  ◇  Config",   "pane-config"),
]


# ─── Dashboard screen ─────────────────────────────────────────────────────────

class DashboardScreen(Screen):
    BINDINGS = [
        Binding("ctrl+q", "app.quit",          "Quit",     show=True),
        Binding("f1",     "go_models",         "Models",   show=False),
        Binding("f2",     "go_chat",           "Chat",     show=False),
        Binding("f3",     "go_history",        "History",  show=False),
        Binding("f4",     "go_memory",         "Memory",   show=False),
        Binding("f5",     "go_hardware",       "Hardware", show=False),
        Binding("f6",     "go_config",         "Config",   show=False),
    ]

    def compose(self) -> ComposeResult:
        yield Horizontal(
            Vertical(
                Static(f" {LOGO}", id="sidebar-logo"),
                ListView(
                    *[
                        ListItem(Label(f" {label}"), id=f"nav-{pane_id}")
                        for label, pane_id in NAV
                    ],
                    id="sidebar-nav",
                ),
                Static("  v0.1.4  Obsidian Neon", id="sidebar-version"),
                id="sidebar",
            ),
            Vertical(
                ContentSwitcher(
                    WelcomePane(id="pane-welcome"),
                    ModelBrowserPane(id="pane-models"),
                    ChatPane(id="pane-chat"),
                    HistoryPane(id="pane-history"),
                    MemoryPane(id="pane-memory"),
                    HardwarePane(id="pane-hardware"),
                    ConfigPane(id="pane-config"),
                    initial="pane-welcome",
                ),
                id="main-area",
            ),
            id="body",
        )
        yield Static("  ◈  AIhub TUI  ·  Ctrl+Q quit  ·  F1-F6 navigate", id="status-bar")

    def on_mount(self) -> None:
        self.set_interval(15, self._tick_status)

    def _tick_status(self) -> None:
        try:
            mem = psutil.virtual_memory()
            used = mem.used / 1e9
            total = mem.total / 1e9
            now = datetime.now().strftime("%H:%M")
            chat_pane = self.query_one("#pane-chat", ChatPane)
            model_str = (
                f"[bold #00e5cc]{chat_pane.current_model}[/bold #00e5cc]"
                if chat_pane.current_model
                else "[#2d3a5e]no model[/#2d3a5e]"
            )
            self.query_one("#status-bar", Static).update(
                f"  ◈ {model_str}  ·  "
                f"[#4a5568]RAM {used:.1f}/{total:.0f}GB  ·  "
                f"Ctrl+Q quit  ·  F1–F6 navigate  ·  [/#4a5568]"
                f"[#b8ff57]{now}[/#b8ff57]"
            )
        except Exception:
            pass

    def switch_pane(self, pane_id: str) -> None:
        self.query_one(ContentSwitcher).current = pane_id
        for _, pid in NAV:
            try:
                item = self.query_one(f"#nav-{pid}", ListItem)
                if pid == pane_id:
                    item.add_class("active")
                else:
                    item.remove_class("active")
            except Exception:
                pass

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        if event.list_view.id == "sidebar-nav":
            item = event.item
            if item and item.id and item.id.startswith("nav-"):
                self.switch_pane(item.id[4:])

    def on_request_start_chat(self, message: RequestStartChat) -> None:
        self.query_one("#pane-chat", ChatPane).start_chat(
            message.model_name, message.context_length
        )
        self.switch_pane("pane-chat")

    def on_request_load_session(self, message: RequestLoadSession) -> None:
        self.query_one("#pane-chat", ChatPane).start_chat(
            message.model_name,
            config.default_context_length,
            messages=message.messages,
        )
        self.switch_pane("pane-chat")

    def action_go_models(self)   -> None: self.switch_pane("pane-models")
    def action_go_chat(self)     -> None: self.switch_pane("pane-chat")
    def action_go_history(self)  -> None: self.switch_pane("pane-history")
    def action_go_memory(self)   -> None: self.switch_pane("pane-memory")
    def action_go_hardware(self) -> None: self.switch_pane("pane-hardware")
    def action_go_config(self)   -> None: self.switch_pane("pane-config")


# ─── App ──────────────────────────────────────────────────────────────────────

class AIHubTUIApp(App):
    TITLE = "AIHub TUI — Obsidian Neon"
    CSS = APP_CSS

    def on_mount(self) -> None:
        self.push_screen(DashboardScreen())

    def on_unmount(self) -> None:
        try:
            screen = self.screen
            if isinstance(screen, DashboardScreen):
                chat_pane = screen.query_one("#pane-chat", ChatPane)
                chat_pane.save_if_needed()
                if chat_pane.current_model:
                    unload_model(chat_pane.current_model)
        except Exception:
            pass


def run() -> None:
    """Entry point: aihub-tui"""
    AIHubTUIApp().run()


launch_tui = run
