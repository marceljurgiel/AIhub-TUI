"""ModelPickerModal — three-tab model browser.

Installed   — Ollama local models + llama.cpp loaded model (existing behaviour)
Live: Ollama — live fetch from Ollama library (ollama pull)
Live: HF GGUF — live fetch from HuggingFace GGUF models (download + llama.cpp)

Returns (model_name, ctx_length, backend) or None on cancel.
backend is "ollama" or "llamacpp".
"""
from __future__ import annotations

import glob
import os
import re
from typing import Any, Dict, List, Optional, Tuple

from textual import work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal
from textual.screen import ModalScreen
from textual.widgets import Button, Input, OptionList, Static, TabbedContent, TabPane
from textual.widgets.option_list import Option

from ...hardware import get_available_ram_gb
from ...models import get_capability_badges, get_speed_label
from ...ollama_client import get_local_model_sizes, is_ollama_running
from .context_config import ContextConfigModal
from .download import DownloadModal


def _ollama_safe_name(stem: str) -> str:
    """A GGUF filename stem → a valid Ollama model name."""
    name = re.sub(r"[^a-zA-Z0-9._-]+", "-", stem).strip("-.").lower()
    return name or "imported-model"


class _ConfirmModal(ModalScreen[bool]):
    """Small yes/no confirmation. Dismisses True on confirm."""

    def __init__(self, message: str, yes_label: str = "Yes",
                 yes_variant: str = "success") -> None:
        super().__init__()
        self._msg = message
        self._yes = yes_label
        self._variant = yes_variant

    def compose(self) -> ComposeResult:
        with Container():
            yield Static(self._msg)
            with Horizontal():
                yield Button(self._yes, id="yes", variant=self._variant)
                yield Button("Cancel", id="no")

    def on_button_pressed(self, e: Button.Pressed) -> None:
        self.dismiss(e.button.id == "yes")


def _delete_model(model_name: str) -> tuple:
    try:
        import requests
        from ...config import config
        resp = requests.delete(
            f"{config.ollama_api_url}/api/delete",
            json={"name": model_name},
            timeout=30,
        )
        if resp.ok:
            return True, ""
        try:
            reason = resp.json().get("error", resp.text)
        except Exception:
            reason = resp.text
        return False, reason
    except Exception as exc:
        return False, str(exc)


class ModelPickerModal(ModalScreen[Optional[Tuple[str, int, str]]]):
    """Returns (model_name, ctx_length, backend) or None."""

    BINDINGS = [
        Binding("escape", "cancel", "Close", show=False),
        Binding("d", "download_selected", "Download", show=False),
        Binding("x", "uninstall_selected", "Uninstall", show=False),
        Binding("r", "refresh_tab", "Refresh", show=False),
    ]

    def __init__(self, registry: List[Dict[str, Any]]) -> None:
        super().__init__()
        self.registry = [m for m in registry if m.get("type") == "chat"]
        self.local_names: set = set()
        self.hw_ram = 0.0
        self._installed_options: list = []
        self._ollama_models: List[Dict] = []
        self._hf_models: List[Dict] = []
        self._ollama_options: list = []
        self._hf_options: list = []
        self._fit_by_name: Dict[str, Dict[str, Any]] = {}
        self._gguf_paths: Dict[str, str] = {}   # stem → downloaded .gguf path
        self._importing = False                 # a gguf→Ollama import is running

    def compose(self) -> ComposeResult:
        with Container():
            yield Static(
                "[b][#a855f7]Pick a model[/#a855f7][/b]   "
                "[#6b6b73]Enter use · D download · X uninstall · R refresh · Esc close[/#6b6b73]",
                id="mp-title",
            )
            yield Static("", id="mp-status")
            with TabbedContent(id="mp-tabs"):
                with TabPane("Installed", id="tab-installed"):
                    yield Input(placeholder="Search installed…", id="mp-search-installed")
                    yield OptionList(id="mp-list-installed")
                with TabPane("Recommended", id="tab-recommend"):
                    yield Static("[#6b6b73]Scoring models for your hardware…[/#6b6b73]", id="mp-recommend-status")
                    yield OptionList(id="mp-list-recommend")
                with TabPane("Ollama Library", id="tab-ollama"):
                    yield Input(
                        placeholder="Search, or type a name + Enter to pull (e.g. gemma3:4b)",
                        id="mp-search-ollama",
                    )
                    yield Static("[#6b6b73]Loading…[/#6b6b73]", id="mp-ollama-status")
                    yield OptionList(id="mp-list-ollama")
                with TabPane("HuggingFace GGUF", id="tab-hf"):
                    yield Input(placeholder="Search HF GGUF…", id="mp-search-hf")
                    yield Static("[#6b6b73]Loading…[/#6b6b73]", id="mp-hf-status")
                    yield OptionList(id="mp-list-hf")
                with TabPane("Cloud API", id="tab-api"):
                    yield Static("", id="mp-api-status")
                    yield OptionList(id="mp-list-api")
            with Horizontal(id="mp-buttons"):
                yield Button("Use", id="mp-use", variant="success")
                yield Button("D Download", id="mp-download")
                yield Button("X Uninstall", id="mp-uninstall", variant="error")
                yield Button("Cancel", id="mp-cancel")

    def on_mount(self) -> None:
        self._refresh_installed()
        self._load_recommend_worker()
        self._load_ollama_worker()
        self._load_hf_worker()
        self._populate_api()
        try:
            self.query_one("#mp-search-installed", Input).focus()
        except Exception:
            pass

    # ── Cloud API tab ─────────────────────────────────────────────────────

    def _populate_api(self) -> None:
        from ...api_models import get_api_models, provider_key_status
        models = get_api_models()
        self._api_models = models
        status_map = provider_key_status()
        ready = [p for p, ok in status_map.items() if ok]
        if ready:
            status = f"[#22c55e]Keys configured: {', '.join(ready)}[/#22c55e]  [#6b6b73]· others need a key in Settings (Ctrl+,)[/#6b6b73]"
        else:
            status = "[#ffb454]No API keys set.[/#ffb454]  [#6b6b73]Add one in Settings (Ctrl+,) to use cloud models.[/#6b6b73]"
        try:
            self.query_one("#mp-api-status", Static).update(status)
        except Exception:
            pass

        opts = []
        for m in models:
            name = m["name"]
            ctx = m.get("context_window", 0)
            ctx_str = f"{ctx // 1000}k" if ctx else "?"
            ready = m.get("key_ready")
            marker = "[#22c55e]✓ ready[/#22c55e]" if ready else "[#6b6b73]needs key[/#6b6b73]"
            colour = "#a855f7" if ready else "#6b6b73"
            desc = m.get("description", "")[:40]
            row = (
                f"[{colour}]{name:<34}[/{colour}]  {marker}  "
                f"[#a8a8b0]ctx {ctx_str}[/#a8a8b0]  [#6b6b73]{desc}[/#6b6b73]"
            )
            opts.append(Option(row, id=m["url"]))   # url is api://provider/model
        if not opts:
            opts.append(Option("(no API models)", id="__none__", disabled=True))
        olist = self.query_one("#mp-list-api", OptionList)
        olist.clear_options()
        olist.add_options(opts)

    # ── Recommended (hardware-fit) tab ─────────────────────────────────────

    @work(thread=True, exclusive=True, group="fit-recommend")
    def _load_recommend_worker(self) -> None:
        from ... import fit
        hw = fit.detect_hw()
        results = fit.recommend(limit=40, hw=hw)
        self.app.call_from_thread(self._populate_recommend, results, hw)

    def _populate_recommend(self, results: list, hw=None) -> None:
        try:
            status = self.query_one("#mp-recommend-status", Static)
            olist = self.query_one("#mp-list-recommend", OptionList)
        except Exception:
            return
        self._fit_by_name = {e["name"]: e for e, _ in results}
        fitting = sum(1 for _, f in results if f.fits)
        # Show what hardware the fit was computed against — so you can confirm
        # the GPU/VRAM was detected correctly (recommendations key off this).
        if hw is not None:
            hw_str = (f"GPU {hw.vram_gb:.0f}GB VRAM" if hw.has_gpu
                      else f"CPU · {hw.ram_gb:.0f}GB RAM")
        else:
            hw_str = "?"
        status.update(
            f"[#a8a8b0]Fit for: {hw_str}[/#a8a8b0]  [#22c55e]· {fitting} fit[/#22c55e]  "
            "[#6b6b73]· best quant picked · Enter to download (llama.cpp)[/#6b6b73]"
        )
        # Header row (column labels) — disabled so it isn't selectable.
        header = (
            f"[#6b6b73]  {'Model':<33}{'Params':>6}  {'Quant':<7}{'Size':>6}  "
            f"{'t/s':>5}  Fit[/#6b6b73]"
        )
        opts = [Option(header, id="__hdr__", disabled=True)]
        for entry, f in results:
            name = entry["name"]
            params = entry.get("parameter_count", "?")
            # Colour by fit quality: green = good, amber = tight/CPU, red = won't fit.
            col = "#ff6e6e" if not f.fits else ("#22c55e" if f.score >= 70 else "#ffb454")
            filled = max(0, min(10, round(f.score / 10)))
            bar = (f"[{col}]{'█' * filled}[/{col}]"
                   f"[#2a2a30]{'░' * (10 - filled)}[/#2a2a30]")
            tps = f"{f.est_tps:.0f}" if f.fits else "—"
            short = (name[:32] + "…") if len(name) > 33 else name
            row = (
                f"[{col}]●[/{col}] [#e6e6e6]{short:<33}[/#e6e6e6]"
                f"[#a8a8b0]{params:>6}[/#a8a8b0]  "
                f"[#a8a8b0]{f.best_quant:<7}[/#a8a8b0]"
                f"[#a8a8b0]{f.size_gb:>5.1f}G[/#a8a8b0]  "
                f"[#6b6b73]{tps:>5}[/#6b6b73]  "
                f"{bar} [{col}]{f.score:>3}[/{col}]"
            )
            opts.append(Option(row, id=f"fit:{name}"))
        if len(opts) == 1:   # only the header → no models
            opts.append(Option("(catalog unavailable)", id="__none__", disabled=True))
        olist.clear_options()
        olist.add_options(opts)

    def _use_fit_model(self, name: str) -> None:
        entry = self._fit_by_name.get(name)
        if not entry:
            return
        sources = entry.get("gguf_sources") or []
        if not sources:
            self.notify(
                f"No GGUF source for {name}. Try the Ollama Library tab "
                "(type the name + Enter to pull).",
                severity="warning",
            )
            return
        repo = sources[0].get("repo")
        self.notify(f"Fetching GGUF files for {repo}…", severity="information")
        self._fetch_gguf_for_fit(repo)

    @work(thread=True, exclusive=True, group="fit-gguf")
    def _fetch_gguf_for_fit(self, repo: str) -> None:
        from ...live_registry import fetch_hf_gguf_files
        from ...config import config
        files = fetch_hf_gguf_files(repo, token=config.hf_api_token)
        self.app.call_from_thread(self._open_fit_gguf, repo, files)

    def _open_fit_gguf(self, repo: str, files: list) -> None:
        if not files:
            self.notify(f"No GGUF files found in {repo}.", severity="warning")
            return
        try:
            from .gguf_picker import GGUFPickerModal
        except ImportError:
            self.notify("GGUF download not available.", severity="warning")
            return
        entry = {"name": repo, "gguf_files": files,
                 "url": f"https://huggingface.co/{repo}"}

        def _after(result) -> None:
            if result:
                model_stem, dest = result
                self._gguf_paths[model_stem] = dest
                self._refresh_installed()
                self._use_downloaded_gguf(model_stem)
        self.app.push_screen(GGUFPickerModal(entry), _after)

    # ── Installed tab ────────────────────────────────────────────────────

    def _refresh_installed(self) -> None:
        from ...config import config
        online = is_ollama_running()
        if online:
            try:
                self.local_names = set(get_local_model_sizes().keys())
            except Exception:
                self.local_names = set()
        try:
            self.hw_ram = get_available_ram_gb()
        except Exception:
            self.hw_ram = 0.0

        # Add llama.cpp loaded model if enabled
        llamacpp_model = ""
        if config.llamacpp_enabled:
            try:
                from ...llamacpp_client import is_llamacpp_running, get_loaded_model
                if is_llamacpp_running():
                    llamacpp_model = get_loaded_model()
            except Exception:
                pass

        status = (
            f"[#a8a8b0]{len(self.local_names)} installed · "
            f"hw {self.hw_ram:.1f} GB · "
            f"{'[#a855f7]● ollama[/#a855f7]' if online else '[#ff6e6e]○ ollama offline[/#ff6e6e]'}"
        )
        if llamacpp_model:
            status += f" · [#22c55e]● llama.cpp: {llamacpp_model}[/#22c55e]"
        status += "[/#a8a8b0]" if "[/#a8a8b0]" not in status else ""
        try:
            self.query_one("#mp-status", Static).update(status)
        except Exception:
            pass

        def _vram(m):
            try:
                return float(m.get("vram_required") or 0)
            except (TypeError, ValueError):
                return 0.0

        recents = list(config.recent_models or [])
        def _recent_rank(name: str) -> int:
            return recents.index(name) if name in recents else 10_000

        # Installed tab shows ONLY installed models (Ollama local + llama.cpp).
        # Recently-used models float to the top, then sort by VRAM (descending).
        installed = [m for m in self.registry if m["name"] in self.local_names]
        installed.sort(key=lambda m: (_recent_rank(m["name"]), -_vram(m)))

        opts: list = []

        # llama.cpp model at the top if present
        if llamacpp_model:
            opts.append(Option(
                f"[#22c55e]● {llamacpp_model:<28}[/#22c55e]  [#6b6b73]llama.cpp  loaded[/#6b6b73]",
                id=f"llamacpp:{llamacpp_model}",
            ))

        for m in installed:
            name = m["name"]
            vram = _vram(m)
            fits = vram <= self.hw_ram if self.hw_ram else True
            speed = get_speed_label(m) or ""
            badges = " ".join(get_capability_badges(m, max_badges=3) or [])
            vram_str = f"{vram:>5.1f}GB" if vram else "    -"
            colour = "#a855f7" if fits else "#a8a8b0"
            recent_tag = "  [#a855f7]· recent[/#a855f7]" if name in recents else ""
            row = (
                f"[{colour}]● {name:<28}[/{colour}]  {vram_str}  "
                f"[#6b6b73]{speed:<12}  {badges}[/#6b6b73]{recent_tag}"
            )
            opts.append(Option(row, id=name))

        # Also surface installed Ollama models not present in the registry
        # (recently-used first).
        registry_names = {m["name"] for m in self.registry}
        extra = sorted(self.local_names - registry_names,
                       key=lambda n: (_recent_rank(n), n))
        for name in extra:
            recent_tag = "  [#a855f7]· recent[/#a855f7]" if name in recents else ""
            opts.append(Option(
                f"[#a855f7]● {name:<28}[/#a855f7]  [#6b6b73]local[/#6b6b73]{recent_tag}",
                id=name,
            ))

        # Downloaded GGUF files (Recommended / HF GGUF tabs) — always visible,
        # even without a running llama-server. Enter imports/uses them.
        self._gguf_paths = {}
        try:
            for path in sorted(glob.glob(
                    os.path.join(config.models_download_dir, "*.gguf"))):
                stem = os.path.splitext(os.path.basename(path))[0]
                self._gguf_paths[stem] = path
                size_gb = os.path.getsize(path) / 1024 ** 3
                short = (stem[:27] + "…") if len(stem) > 28 else stem
                imported = self._gguf_imported_name(stem)
                if size_gb < 0.05:
                    tag = "[#ff6e6e]gguf · incomplete download?[/#ff6e6e]"
                elif imported:
                    tag = "[#22c55e]✓ imported · Enter to run[/#22c55e]"
                else:
                    tag = "[#6b6b73]gguf · Enter to import & run[/#6b6b73]"
                opts.append(Option(
                    f"[#a8a8b0]◆ {short:<28}[/#a8a8b0]  {size_gb:>5.1f}GB  {tag}",
                    id=f"gguf-file:{stem}",
                ))
        except Exception:
            pass

        if not opts:
            opts.append(Option(
                "(no models installed — see Ollama Library / HF GGUF tabs)",
                id="__none__", disabled=True,
            ))

        self._installed_options = opts
        olist = self.query_one("#mp-list-installed", OptionList)
        olist.clear_options()
        olist.add_options(opts)

    # ── Ollama library tab ────────────────────────────────────────────────

    @work(thread=True, exclusive=True, group="live-ollama")
    def _load_ollama_worker(self) -> None:
        from ...live_registry import fetch_ollama_library, get_live_error
        from ...config import config
        models = fetch_ollama_library(limit=config.ollama_library_limit)
        self.app.call_from_thread(self._populate_ollama, models)

    def _populate_ollama(self, models: List[Dict]) -> None:
        from ...live_registry import get_live_error
        err = get_live_error(models)
        try:
            status = self.query_one("#mp-ollama-status", Static)
            olist = self.query_one("#mp-list-ollama", OptionList)
        except Exception:
            return
        if err:
            status.update(f"[#ff6e6e]{err}[/#ff6e6e]")
            return
        status.update(
            f"[#22c55e]{len(models)} most-popular models[/#22c55e]  "
            "[#6b6b73]Enter to pick a size that fits your device · type to filter[/#6b6b73]"
        )
        self._ollama_models = models
        opts = self._build_ollama_opts(models)
        self._ollama_options = opts
        olist.clear_options()
        olist.add_options(opts)

    def _build_ollama_opts(self, models: List[Dict]) -> list:
        import re as _re
        opts = []
        for m in models:
            name = m.get("name", "")
            installed = name in self.local_names
            marker = "[#22c55e]✓ installed[/#22c55e]" if installed else "[#6b6b73]pick size →[/#6b6b73]"
            # Show the distinct parameter sizes available (1b, 4b, 12b…)
            tags = m.get("tags") or []
            sizes = []
            for t in tags:
                sm = _re.match(r"^(\d+(?:\.\d+)?b)$", t, _re.IGNORECASE)
                if sm:
                    sizes.append(sm.group(1))
            sizes_str = ", ".join(sizes[:6]) if sizes else "default"
            row = (
                f"[#a855f7]{name:<26}[/#a855f7]  {marker}  "
                f"[#a8a8b0]sizes:[/#a8a8b0] [#6b6b73]{sizes_str}[/#6b6b73]"
            )
            opts.append(Option(row, id=f"ollama:{name}"))
        if not opts:
            opts.append(Option("(no results)", id="__none__", disabled=True))
        return opts

    # ── HF GGUF tab ───────────────────────────────────────────────────────

    @work(thread=True, exclusive=True, group="live-hf")
    def _load_hf_worker(self, query: str = "") -> None:
        from ...live_registry import fetch_hf_gguf_models, get_live_error
        from ...config import config
        models = fetch_hf_gguf_models(
            query=query, limit=config.hf_gguf_limit, token=config.hf_api_token,
        )
        self.app.call_from_thread(self._populate_hf, models)

    def _populate_hf(self, models: List[Dict]) -> None:
        from ...live_registry import get_live_error
        err = get_live_error(models)
        try:
            status = self.query_one("#mp-hf-status", Static)
            olist = self.query_one("#mp-list-hf", OptionList)
        except Exception:
            return
        if err:
            status.update(f"[#ff6e6e]{err}[/#ff6e6e]")
            return
        status.update(
            f"[#22c55e]{len(models)} models[/#22c55e]  "
            "[#6b6b73]Enter to pick quant & download · type to filter[/#6b6b73]"
        )
        self._hf_models = models
        opts = self._build_hf_opts(models)
        self._hf_options = opts
        olist.clear_options()
        olist.add_options(opts)

    def _build_hf_opts(self, models: List[Dict]) -> list:
        opts = []
        for m in models:
            name = m.get("name", "")
            size = m.get("size_gb", 0)
            nfiles = len(m.get("gguf_files") or [])
            desc = m.get("description", "")[:40]
            size_str = f"{size:.1f}GB" if size else "?GB"
            row = (
                f"[#a855f7]{name:<45}[/#a855f7]  "
                f"[#a8a8b0]{size_str}  {nfiles} files[/#a8a8b0]  "
                f"[#6b6b73]{desc}[/#6b6b73]"
            )
            opts.append(Option(row, id=f"hf:{name}"))
        if not opts:
            opts.append(Option("(no results)", id="__none__", disabled=True))
        return opts

    # ── Search / filter ───────────────────────────────────────────────────

    def on_input_changed(self, event: Input.Changed) -> None:
        needle = event.value.strip().lower()
        if event.input.id == "mp-search-installed":
            olist = self.query_one("#mp-list-installed", OptionList)
            olist.clear_options()
            if not needle:
                olist.add_options(self._installed_options)
            else:
                filtered = [o for o in self._installed_options
                            if o.id and needle in o.id.lower()]
                olist.add_options(filtered or [Option("(no match)", id="__none__", disabled=True)])

        elif event.input.id == "mp-search-ollama":
            olist = self.query_one("#mp-list-ollama", OptionList)
            olist.clear_options()
            if not needle:
                olist.add_options(self._ollama_options)
            else:
                filtered = [o for o in self._ollama_options
                            if o.id and needle in o.id.lower()]
                olist.add_options(filtered or [Option("(no match)", id="__none__", disabled=True)])

        elif event.input.id == "mp-search-hf":
            # For HF, trigger a real API search after a short delay
            olist = self.query_one("#mp-list-hf", OptionList)
            olist.clear_options()
            olist.add_options([Option("[#6b6b73]Searching…[/#6b6b73]", id="__none__", disabled=True)])
            self._load_hf_worker(query=needle)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        # Enter in the Ollama search box pulls that exact model name — works for
        # any model, even ones the (stale) library mirror doesn't list.
        if event.input.id == "mp-search-ollama":
            name = event.value.strip()
            if name:
                self._install_and_use(name)

    # ── Selection ─────────────────────────────────────────────────────────

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        self._dispatch_use(event.option_id)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "mp-cancel":
            self.dismiss(None)
        elif event.button.id == "mp-use":
            self._dispatch_use(self._highlighted_id())
        elif event.button.id == "mp-download":
            self.action_download_selected()
        elif event.button.id == "mp-uninstall":
            self.action_uninstall_selected()

    def _highlighted_id(self) -> Optional[str]:
        try:
            tab = self._active_tab()
            olist_id = f"mp-list-{tab}"
            olist = self.query_one(f"#{olist_id}", OptionList)
            idx = olist.highlighted
            opt = olist.get_option_at_index(idx) if idx is not None else None
            return opt.id if opt else None
        except Exception:
            return None

    def _active_tab(self) -> str:
        try:
            active = self.query_one("#mp-tabs", TabbedContent).active
            return active.replace("tab-", "")
        except Exception:
            return "installed"

    def _dispatch_use(self, opt_id: Optional[str]) -> None:
        if not opt_id or opt_id.startswith("__"):   # __none__, __hdr__
            return
        if opt_id.startswith("api://"):
            self._use_api_model(opt_id)
        elif opt_id.startswith("fit:"):
            self._use_fit_model(opt_id[len("fit:"):])
        elif opt_id.startswith("llamacpp:"):
            model = opt_id[len("llamacpp:"):]
            self._open_ctx(model, backend="llamacpp")
        elif opt_id.startswith("ollama:"):
            name = opt_id[len("ollama:"):]
            self._use_ollama_library(name)
        elif opt_id.startswith("hf:"):
            model_id = opt_id[len("hf:"):]
            self._open_gguf_picker(model_id)
        elif opt_id.startswith("gguf-file:"):
            self._use_downloaded_gguf(opt_id[len("gguf-file:"):])
        else:
            # Installed tab (plain name)
            if opt_id not in self.local_names:
                self._install_ollama(opt_id)
            else:
                self._open_ctx(opt_id, backend="ollama")

    def _open_ctx(self, model_name: str, backend: str = "ollama") -> None:
        def _after_ctx(ctx: Optional[int]) -> None:
            if ctx is None:
                return
            self.dismiss((model_name, ctx, backend))
        self.app.push_screen(ContextConfigModal(model_name), _after_ctx)

    def _use_api_model(self, api_url: str) -> None:
        entry = next((m for m in getattr(self, "_api_models", []) if m["url"] == api_url), None)
        if entry and not entry.get("key_ready"):
            provider = entry.get("provider", "this provider")
            self.notify(
                f"No API key for {provider}. Add it in Settings (Ctrl+,) first.",
                severity="warning",
            )
            return
        from ...config import config
        # API models don't need a KV-cache estimate; use the default context.
        self.dismiss((api_url, config.default_context_length, "api"))

    def _use_ollama_library(self, name: str) -> None:
        """Selected a model from the Ollama library tab.

        If it has multiple size variants, open the variant picker so the user
        chooses which (e.g. gemma3:4b). Otherwise pull the bare name.
        """
        entry = next((m for m in self._ollama_models if m.get("name") == name), None)
        tags = (entry.get("tags") if entry else None) or []
        # Tags that name a concrete pullable variant (have a parameter size)
        import re as _re
        sized = [t for t in tags if _re.search(r"\d+(\.\d+)?\s*b\b", t, _re.IGNORECASE)]

        if sized:
            from .ollama_variant import OllamaVariantModal

            def _after_variant(full_tag) -> None:
                if not full_tag:
                    return
                # full_tag like "gemma3:4b" — install then use
                self._install_and_use(full_tag)
            self.app.push_screen(OllamaVariantModal(entry), _after_variant)
        else:
            # No size variants — pull the bare name
            if name in self.local_names:
                self._open_ctx(name, backend="ollama")
            else:
                self._install_and_use(name)

    def _install_and_use(self, model_name: str) -> None:
        """Install (if needed) then proceed to context config + use."""
        if model_name in self.local_names:
            self._open_ctx(model_name, backend="ollama")
            return

        def _after(success: bool) -> None:
            if success:
                self.notify(f"{model_name} installed!", severity="information")
                self.local_names.add(model_name)
                self._open_ctx(model_name, backend="ollama")
            else:
                self.notify("Install failed or cancelled.", severity="warning")
        self.app.push_screen(DownloadModal(model_name), _after)

    def _install_ollama(self, model_name: str) -> None:
        def _after(success: bool) -> None:
            if success:
                self.notify(f"{model_name} installed!", severity="information")
                self._refresh_installed()
            else:
                self.notify("Install failed or cancelled.", severity="warning")
        self.app.push_screen(DownloadModal(model_name), _after)

    def _open_gguf_picker(self, model_id: str) -> None:
        model_entry = next((m for m in self._hf_models if m["name"] == model_id), None)
        if not model_entry:
            return
        try:
            from .gguf_picker import GGUFPickerModal
        except ImportError:
            self.notify("GGUF download (Phase D) not yet implemented.", severity="warning")
            return

        def _after(result) -> None:
            if result:
                model_stem, dest_path = result
                self._gguf_paths[model_stem] = dest_path
                self._refresh_installed()
                self._use_downloaded_gguf(model_stem)
        self.app.push_screen(GGUFPickerModal(model_entry), _after)

    # ── Downloaded GGUF files (Recommended / HF tabs land here) ──────────

    def _gguf_imported_name(self, stem: str) -> str:
        """Ollama model name if this downloaded gguf is already imported."""
        name = _ollama_safe_name(stem)
        if name in self.local_names or f"{name}:latest" in self.local_names:
            return name
        return ""

    def _use_downloaded_gguf(self, stem: str) -> None:
        """Run a .gguf from models_download_dir — touchless: already
        imported → straight to run; otherwise auto-import into Ollama
        (one-time) and run. llama-server is only used if it already has
        this exact model loaded."""
        from ...config import config
        path = self._gguf_paths.get(stem, "")

        # Already imported into Ollama → just run it. Except: imports made
        # before v0.3.11 got the raw '{{ .Prompt }}' template (no chat
        # wrapping → gibberish replies) — re-import once to heal them.
        imported = self._gguf_imported_name(stem)
        if imported:
            healed = True
            if path and os.path.exists(path) and not getattr(self, "_importing", False):
                try:
                    from ...ollama_client import model_template
                    from ...gguf import detect_chat_format
                    if (model_template(imported) == "{{ .Prompt }}"
                            and detect_chat_format(path)):
                        healed = False
                except Exception:
                    healed = True
            if healed:
                self._open_ctx(imported, backend="ollama")
            else:
                self._importing = True
                self.notify(
                    f"Upgrading {imported} with a proper chat template "
                    "(one-time fix)…", severity="information", timeout=8)
                self._import_gguf_worker(path, imported)
            return

        # An already-running llama-server serving this file also counts.
        if config.llamacpp_enabled:
            try:
                from ...llamacpp_client import is_llamacpp_running, get_loaded_model
                if is_llamacpp_running():
                    loaded = os.path.splitext(os.path.basename(
                        get_loaded_model() or ""))[0]
                    if loaded and (loaded.lower() == stem.lower()):
                        self._open_ctx(stem, backend="llamacpp")
                        return
            except Exception:
                pass

        if not path or not os.path.exists(path):
            self.notify(f"File for {stem} not found — re-download it.",
                        severity="warning")
            return
        if os.path.getsize(path) < 0.05 * 1024 ** 3:
            self.notify(
                f"{stem} looks like an incomplete download "
                f"({os.path.getsize(path) / 1024**2:.0f} MB) — re-download it "
                "before running.", severity="warning", timeout=10)
            return

        if is_ollama_running():
            if getattr(self, "_importing", False):
                self.notify("An import is already running…", severity="warning")
                return
            name = _ollama_safe_name(stem)
            self._importing = True
            self.notify(
                f"Importing {stem} into Ollama — one-time setup, "
                "usually 10–60 s…", severity="information", timeout=8)
            try:
                self.query_one("#mp-status", Static).update(
                    f"[#a855f7]⏳ Importing {stem}… (hashing + upload)[/#a855f7]")
            except Exception:
                pass
            self._import_gguf_worker(path, name)
        else:
            self.notify(
                "Ollama is offline — start it (`ollama serve`) and press "
                "Enter on this model again.\nOr serve it directly with: "
                f"llama-server --model {path} --port 8080",
                severity="warning", timeout=12,
            )

    @work(thread=True, exclusive=True, group="gguf-import")
    def _import_gguf_worker(self, path: str, name: str) -> None:
        from ...ollama_client import import_gguf_model
        ok, err = import_gguf_model(path, name)

        def done() -> None:
            self._importing = False
            if ok:
                self.notify(f"Imported as {name} ✓ — starting…",
                            severity="information")
                self.local_names.add(f"{name}:latest")
                self._refresh_installed()
                self._open_ctx(name, backend="ollama")
            else:
                try:
                    self.query_one("#mp-status", Static).update(
                        f"[#ff6e6e]Import failed: {err}[/#ff6e6e]")
                except Exception:
                    pass
                self.notify(f"Import failed: {err}", severity="error",
                            timeout=12)
        try:
            self.app.call_from_thread(done)
        except Exception:
            self._importing = False

    # ── Actions ───────────────────────────────────────────────────────────

    def action_download_selected(self) -> None:
        opt_id = self._highlighted_id()
        if not opt_id or opt_id == "__none__":
            return
        if opt_id.startswith("hf:"):
            self._open_gguf_picker(opt_id[3:])
        elif opt_id.startswith("ollama:"):
            # Route through the variant picker so the user chooses the size.
            self._use_ollama_library(opt_id[len("ollama:"):])
        else:
            name = opt_id.replace("llamacpp:", "")
            if name in self.local_names:
                self.notify(f"{name} is already installed.", severity="information")
                return
            self._install_ollama(name)

    def action_uninstall_selected(self) -> None:
        opt_id = self._highlighted_id()
        if opt_id and opt_id.startswith("gguf-file:"):
            self._confirm_delete_gguf(opt_id[len("gguf-file:"):])
            return
        if not opt_id or opt_id == "__none__" or opt_id.startswith(("ollama:", "hf:", "llamacpp:")):
            self.notify("Select an installed model from the Installed tab.", severity="warning")
            return
        if opt_id not in self.local_names:
            self.notify(f"{opt_id} is not installed.", severity="warning")
            return
        self._confirm_uninstall(opt_id)

    def _confirm_uninstall(self, model_name: str) -> None:
        from textual.app import ComposeResult as CR
        from textual.containers import Container as Ct, Horizontal as H
        from textual.screen import ModalScreen as MS
        from textual.widgets import Button as B, Static as S

        class Confirm(MS):
            def __init__(self, n):
                super().__init__(); self._n = n
            def compose(self) -> CR:
                with Ct():
                    yield S(f"[b]Uninstall[/b] [#a855f7]{self._n}[/#a855f7]?\n\n[#6b6b73]This will delete the model files.[/#6b6b73]")
                    with H():
                        yield B("Yes, uninstall", id="yes", variant="error")
                        yield B("Cancel", id="no")
            def on_button_pressed(self, e: B.Pressed): self.dismiss(e.button.id == "yes")

        def _after(confirmed: bool) -> None:
            if not confirmed:
                return
            ok, err = _delete_model(model_name)
            if ok:
                self.notify(f"Uninstalled {model_name}.", severity="information")
                self._refresh_installed()
            else:
                self.notify(f"Failed: {err}", severity="error")

        self.app.push_screen(Confirm(model_name), _after)

    def _confirm_delete_gguf(self, stem: str) -> None:
        path = self._gguf_paths.get(stem, "")
        if not path:
            return
        msg = (f"[b]Delete[/b] [#a855f7]{stem}[/#a855f7]?\n\n"
               f"[#6b6b73]Removes the downloaded file:\n{path}[/#6b6b73]")

        def _after(confirmed: Optional[bool]) -> None:
            if not confirmed:
                return
            try:
                os.remove(path)
                self.notify(f"Deleted {stem}.", severity="information")
            except Exception as exc:
                self.notify(f"Delete failed: {exc}", severity="error")
            self._refresh_installed()
        self.app.push_screen(
            _ConfirmModal(msg, yes_label="Delete", yes_variant="error"), _after)

    def action_refresh_tab(self) -> None:
        tab = self._active_tab()
        if tab == "installed":
            self._refresh_installed()
        elif tab == "recommend":
            self._load_recommend_worker()
        elif tab == "ollama":
            self._load_ollama_worker()
        elif tab == "hf":
            self._load_hf_worker()

    def action_cancel(self) -> None:
        self.dismiss(None)
