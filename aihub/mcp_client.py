"""
AIHub — MCP (Model Context Protocol) servers as tools.

Servers are configured in ~/.aihub/mcp.json, in the same format Claude
Desktop uses (so configs from READMEs paste in as-is), plus a few AIHub
fields per server:

    {"mcpServers": {
        "gmail": {"command": "workspace-mcp", "args": ["--tools", "gmail"],
                  "env": {"GOOGLE_OAUTH_CLIENT_ID": "…"},
                  "enabled": true,
                  "keywords": ["mail", "gmail", "inbox", "poczt"],
                  "disabledTools": ["delete_gmail_message"]},
        "remote": {"url": "https://example.com/mcp"}
    }}

Each server's tools become model tools named `<server>__<tool>`. They are
offered only when a request is about that server (its keywords) or to an
agent that lists `mcp:<server>` — small models drown in long tool lists.

Safety: a tool the server marks read-only runs freely; every other one
(send, delete, change…) asks the user first, in every mode. What a server
returns (email bodies, web pages) is data, never instructions.

Connections: one background asyncio loop; each server gets one long-lived
task that opens the connection, serves calls from a queue and closes it —
the SDK's task groups must be entered and exited by the same task.
"""
from __future__ import annotations

import asyncio
import concurrent.futures
import json
import logging
import os
import re
import sys
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from .config import CONFIG_DIR

log = logging.getLogger(__name__)

SEP = "__"
CONNECT_TIMEOUT = 90          # first start may download a server (npx, pip)
CALL_TIMEOUT = 120
_NAME = re.compile(r"[^A-Za-z0-9_-]+")


def config_path() -> str:
    return os.path.join(CONFIG_DIR, "mcp.json")


def log_path() -> str:
    return os.path.join(CONFIG_DIR, "logs", "mcp-servers.log")


def safe_name(name: str) -> str:
    return _NAME.sub("_", name).strip("_")[:24] or "server"


# ── Config ───────────────────────────────────────────────────────────────────

def load_config() -> Dict[str, Dict[str, Any]]:
    try:
        with open(config_path(), encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        return {}
    except Exception as exc:
        log.warning("mcp.json unreadable: %s", exc)
        return {}
    servers = data.get("mcpServers", data) if isinstance(data, dict) else {}
    return {k: v for k, v in servers.items() if isinstance(v, dict)}


def save_config(servers: Dict[str, Dict[str, Any]]) -> None:
    os.makedirs(os.path.dirname(config_path()), exist_ok=True)
    tmp = config_path() + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"mcpServers": servers}, f, indent=2, ensure_ascii=False)
    os.replace(tmp, config_path())
    try:
        os.chmod(config_path(), 0o600)        # may hold OAuth client secrets
    except OSError:
        pass


def parse_server_entry(text: str) -> Dict[str, Dict[str, Any]]:
    """What a user pastes to add servers: a Claude Desktop JSON block
    ({"mcpServers": {...}} or just {...}), a single {"command": …} object
    with no name, or a command line ("npx -y @scope/server --flag")."""
    t = (text or "").strip()
    if not t:
        raise ValueError("paste a JSON block or a command line")
    if t.startswith("{"):
        try:
            data = json.loads(t)
        except ValueError as exc:
            raise ValueError(f"that JSON doesn't parse: {exc}")
        if "mcpServers" in data:
            data = data["mcpServers"]
        if "command" in data or "url" in data:
            return {_guess_name(data): data}
        servers = {k: v for k, v in data.items() if isinstance(v, dict) and ("command" in v or "url" in v)}
        if not servers:
            raise ValueError("no server in that JSON (each needs a command or a url)")
        return servers
    if re.match(r"^https?://", t):
        return {_guess_name({"url": t}): {"url": t}}
    import shlex
    parts = shlex.split(t)
    return {_guess_name({"command": parts[0], "args": parts[1:]}): {"command": parts[0], "args": parts[1:]}}


def _guess_name(entry: Dict[str, Any]) -> str:
    if entry.get("url"):
        from urllib.parse import urlparse
        return safe_name(urlparse(entry["url"]).hostname or "remote")
    words = [str(w) for w in [entry.get("command", "")] + list(entry.get("args") or []) if w]
    # Prefer what looks like the server package/script, not option values.
    looks = [w for w in words if not w.startswith("-") and (
        w.startswith("@") or re.search(r"mcp|server", w, re.I) or w.endswith((".py", ".js")))]
    for w in looks + [w for w in reversed(words) if not w.startswith("-")]:
        base = w.rsplit("/", 1)[-1]
        base = base.split("@")[0] if not base.startswith("@") else base[1:].split("@")[0]
        base = re.sub(r"^(mcp-server-|server-|mcp-)|(-mcp|-server|\.py|\.js)$", "", base)
        if base and base not in ("npx", "uvx", "node", "python", "python3", "-y", "mcp", "server"):
            return safe_name(base)
    return "server"


# ── Connections ──────────────────────────────────────────────────────────────

@dataclass
class Server:
    name: str
    cfg: Dict[str, Any]
    status: str = "stopped"           # stopped | starting | connected | error
    error: str = ""
    tools: List[Any] = field(default_factory=list)
    queue: Optional[asyncio.Queue] = None
    task: Optional[asyncio.Task] = None
    ready: Optional[asyncio.Event] = None
    started_at: float = 0.0


class Manager:
    def __init__(self) -> None:
        # Stray non-JSON lines from a server's stdout are harmless; the SDK
        # logs each with a full traceback, which would flood the bridge log.
        logging.getLogger("mcp.client.stdio").setLevel(logging.CRITICAL)
        self.loop = asyncio.new_event_loop()
        self.thread = threading.Thread(target=self.loop.run_forever, name="aihub-mcp", daemon=True)
        self.thread.start()
        self.servers: Dict[str, Server] = {}
        self.lock = threading.Lock()

    # sync helpers ------------------------------------------------------------
    def _run(self, coro, timeout: float):
        fut = asyncio.run_coroutine_threadsafe(coro, self.loop)
        try:
            return fut.result(timeout)
        except concurrent.futures.TimeoutError:
            fut.cancel()
            raise TimeoutError(f"no answer within {int(timeout)} s")

    def server(self, name: str) -> Server:
        cfg = load_config().get(name)
        if cfg is None:
            raise KeyError(f"no MCP server named {name!r}")
        with self.lock:
            s = self.servers.get(name)
            if s is None or s.cfg != cfg:
                if s is not None:
                    self.stop(name)
                s = Server(name, cfg)
                self.servers[name] = s
        return s

    def ensure(self, name: str) -> Server:
        """Connected server (starting it if needed); raises with the reason."""
        s = self.server(name)
        if s.status == "connected":
            return s
        if s.status != "starting":
            self._run(self._start(s), 5)
        self._run(self._wait_ready(s), CONNECT_TIMEOUT)
        if s.status != "connected":
            raise RuntimeError(s.error or f"{name} didn't start")
        return s

    def call(self, name: str, tool: str, args: Dict[str, Any], timeout: float = CALL_TIMEOUT):
        s = self.ensure(name)
        try:
            return self._run(self._call(s, tool, args), timeout + 5)
        except ConnectionError:
            # The server died (or closed the session): one restart, then give up.
            log.info("mcp %s: reconnecting", name)
            self.stop(name)
            s = self.ensure(name)
            return self._run(self._call(s, tool, args), timeout + 5)

    def stop(self, name: str) -> None:
        s = self.servers.get(name)
        if not s or not s.task or s.task.done():
            if s:
                s.status = "stopped"
            return
        try:
            self._run(self._stop(s), 10)
        except Exception:
            pass
        s.status = "stopped"

    def stop_all(self) -> None:
        for name in list(self.servers):
            self.stop(name)

    # async side ----------------------------------------------------------------
    async def _start(self, s: Server) -> None:
        s.queue = asyncio.Queue()
        s.ready = asyncio.Event()
        s.status, s.error, s.started_at = "starting", "", time.time()
        s.task = asyncio.ensure_future(self._worker(s))

    async def _wait_ready(self, s: Server) -> None:
        if s.ready is not None:
            await s.ready.wait()

    async def _stop(self, s: Server) -> None:
        if s.queue is not None and s.task and not s.task.done():
            fut = self.loop.create_future()
            await s.queue.put(("stop", None, fut))
            try:
                await asyncio.wait_for(asyncio.shield(s.task), 8)
            except Exception:
                s.task.cancel()

    async def _call(self, s: Server, tool: str, args: Dict[str, Any]):
        if s.task is None or s.task.done():
            raise ConnectionError("server not running")
        fut = self.loop.create_future()
        await s.queue.put(("call", (tool, args), fut))
        return await fut

    def _transport(self, s: Server):
        from mcp import StdioServerParameters
        from mcp.client.stdio import stdio_client
        cfg = s.cfg
        if cfg.get("url"):
            if cfg.get("headers"):
                # Tokens (Home Assistant, GitHub remote…) go in the headers.
                from mcp.client.streamable_http import create_mcp_http_client, streamable_http_client
                client = create_mcp_http_client(headers={k: str(v) for k, v in cfg["headers"].items()})
                return streamable_http_client(cfg["url"], http_client=client)
            return cfg["url"]
        env = {**os.environ, **{k: str(v) for k, v in (cfg.get("env") or {}).items()}}
        # npx prints "added 39 packages…" to stdout on first run, which isn't
        # protocol traffic: keep npm quiet.
        env.setdefault("npm_config_loglevel", "silent")
        env.setdefault("npm_config_fund", "false")
        env.setdefault("npm_config_audit", "false")
        env.setdefault("npm_config_update_notifier", "false")
        import shutil as _sh
        command = str(cfg["command"])
        # Windows: "npx" is npx.cmd — resolve through PATH/PATHEXT.
        command = _sh.which(command, path=env.get("PATH")) or command
        params = StdioServerParameters(command=command, args=[str(a) for a in cfg.get("args") or []],
                                       env=env, cwd=cfg.get("cwd") or None)
        os.makedirs(os.path.dirname(log_path()), exist_ok=True)
        errlog = open(log_path(), "a", encoding="utf-8")
        errlog.write(f"\n--- {time.strftime('%Y-%m-%d %H:%M:%S')} start {s.name}: {cfg['command']} {' '.join(map(str, cfg.get('args') or []))}\n")
        errlog.flush()
        return stdio_client(params, errlog=errlog), errlog

    async def _worker(self, s: Server) -> None:
        from mcp import Client
        errlog = None
        try:
            transport = self._transport(s)
            if isinstance(transport, tuple):
                transport, errlog = transport
            async with Client(transport) as client:
                tools, cursor = [], None
                while True:
                    res = await client.list_tools(cursor) if cursor else await client.list_tools()
                    tools += list(res.tools)
                    cursor = getattr(res, "next_cursor", None)
                    if not cursor:
                        break
                s.tools, s.status = tools, "connected"
                s.ready.set()
                while True:
                    kind, payload, fut = await s.queue.get()
                    if kind == "stop":
                        fut.set_result(None)
                        break
                    tool, args = payload
                    try:
                        result = await asyncio.wait_for(client.call_tool(tool, args), CALL_TIMEOUT)
                        if not fut.done():
                            fut.set_result(result)
                    except Exception as exc:
                        dead = _is_disconnect(exc)
                        if not fut.done():
                            fut.set_exception(ConnectionError(str(exc)) if dead else exc)
                        if dead:
                            break
        except BaseException as exc:          # ExceptionGroup from the SDK's task groups
            s.error = _reason(exc)
            log.info("mcp %s failed: %s", s.name, s.error)
        finally:
            s.status = "error" if s.error else "stopped"
            if s.ready is not None:
                s.ready.set()
            # Anything still queued gets an answer instead of hanging.
            while s.queue is not None and not s.queue.empty():
                _, _, fut = s.queue.get_nowait()
                if not fut.done():
                    fut.set_exception(ConnectionError(s.error or "server stopped"))
            if errlog:
                errlog.close()


def _flatten(exc: BaseException) -> List[BaseException]:
    if isinstance(exc, BaseExceptionGroup):
        out = []
        for e in exc.exceptions:
            out += _flatten(e)
        return out
    return [exc]


def _reason(exc: BaseException) -> str:
    leaves = _flatten(exc)
    for e in leaves:
        if isinstance(e, FileNotFoundError):
            return f"command not found: {e.filename or e}"
    text = "; ".join(f"{type(e).__name__}: {e}" for e in leaves if str(e))[:300]
    return text or type(exc).__name__


def _is_disconnect(exc: BaseException) -> bool:
    msg = str(exc).lower()
    return "connection closed" in msg or "broken pipe" in msg or isinstance(exc, (BrokenPipeError, EOFError))


_MANAGER: Optional[Manager] = None
_MANAGER_LOCK = threading.Lock()


def manager() -> Manager:
    global _MANAGER
    with _MANAGER_LOCK:
        if _MANAGER is None:
            _MANAGER = Manager()
        return _MANAGER


def shutdown() -> None:
    if _MANAGER is not None:
        _MANAGER.stop_all()


# ── Tools for the model ─────────────────────────────────────────────────────

def _ann(tool: Any) -> Dict[str, Any]:
    a = getattr(tool, "annotations", None)
    return a.model_dump(exclude_none=True) if a is not None else {}


def is_read_only(tool: Any) -> bool:
    return bool(_ann(tool).get("read_only_hint"))


def _clean_schema(schema: Dict[str, Any]) -> Dict[str, Any]:
    """Input schema for Ollama/OpenAI: object type, local $refs inlined (one
    level), titles dropped (noise for small models)."""
    schema = json.loads(json.dumps(schema or {}))
    defs = schema.pop("$defs", None) or schema.pop("definitions", None) or {}

    def walk(node):
        if isinstance(node, dict):
            ref = node.get("$ref")
            if isinstance(ref, str) and ref.split("/")[-1] in defs:
                node = {**defs[ref.split("/")[-1]], **{k: v for k, v in node.items() if k != "$ref"}}
            out_ = {k: walk(v) for k, v in node.items() if k != "title"}
            d = out_.get("description")
            if isinstance(d, str) and len(d) > 140:      # parameter docs: keep them short
                out_["description"] = d[:139] + "…"
            return out_
        if isinstance(node, list):
            return [walk(v) for v in node]
        return node
    out = walk(schema)
    out.setdefault("type", "object")
    out.setdefault("properties", {})
    return out


def full_name(server: str, tool: str) -> str:
    return f"{safe_name(server)}{SEP}{tool}"[:64]


def split_name(name: str) -> Optional[Tuple[str, str]]:
    if SEP not in (name or ""):
        return None
    server_part, tool = name.split(SEP, 1)
    for server in load_config():
        if safe_name(server) == server_part:
            return server, tool
    return None


def enabled_servers() -> Dict[str, Dict[str, Any]]:
    return {k: v for k, v in load_config().items() if v.get("enabled", True)}


def tool_schemas(server: str, only: Optional[List[str]] = None) -> List[Dict[str, Any]]:
    """Function schemas for a server's enabled tools (connects if needed;
    a server that can't start contributes none)."""
    try:
        s = manager().ensure(server)
    except Exception as exc:
        log.info("mcp %s unavailable: %s", server, exc)
        return []
    off = set(s.cfg.get("disabledTools") or [])
    allow = set(s.cfg.get("tools") or [])
    out = []
    for t in s.tools:
        if t.name in off or (allow and t.name not in allow) or (only and t.name not in only):
            continue
        desc = " ".join((t.description or "").split())
        # First sentences only: tool docs often run to whole manuals.
        if len(desc) > 240:
            cut = desc[:240].rsplit(". ", 1)[0]
            desc = (cut if len(cut) > 80 else desc[:239]) + "…"
        tag = "" if is_read_only(t) else " (changes things — the user approves each call)"
        params = _clean_schema(getattr(t, "input_schema", {}) or {})
        # Arguments AIhub fills itself ("defaultArgs", e.g. the user's address)
        # aren't the model's business: hide them.
        for k in (s.cfg.get("defaultArgs") or {}):
            params.get("properties", {}).pop(k, None)
            if isinstance(params.get("required"), list):
                params["required"] = [r for r in params["required"] if r != k]
        out.append({"type": "function", "function": {
            "name": full_name(server, t.name),
            "description": f"[{server}] {desc}{tag}",
            "parameters": params,
        }})
    return out


def _words(text: str) -> List[str]:
    return re.findall(r"[a-ząćęłńóśźż0-9]+", (text or "").lower())


def servers_for(text: str) -> List[str]:
    """Enabled servers a message is about: it names the server or one of its
    keywords (prefix match, so "mailu" ~ "mail")."""
    words = _words(text)
    hits = []
    for name, cfg in enabled_servers().items():
        keys = [k.lower() for k in (cfg.get("keywords") or [])] + [name.lower()]
        if any(w.startswith(k) for k in keys for w in words if len(k) >= 3):
            hits.append(name)
    return hits


def schemas_for_message(text: str) -> List[Dict[str, Any]]:
    out = []
    for server in servers_for(text):
        out += tool_schemas(server)
    return out


def schemas_for_agent(entries: List[str]) -> List[Dict[str, Any]]:
    """Agent tool entries 'mcp:gmail' (all its tools) or 'mcp:gmail/search'."""
    out = []
    picks: Dict[str, List[str]] = {}
    for e in entries:
        if not e.startswith("mcp:"):
            continue
        server, _, tool = e[4:].partition("/")
        if server in enabled_servers():
            picks.setdefault(server, [])
            if tool:
                picks[server].append(tool)
    for server, tools in picks.items():
        out += tool_schemas(server, tools or None)
    return out


def _tool(server: str, tool: str):
    s = manager().servers.get(server)
    return next((t for t in (s.tools if s else []) if t.name == tool), None)


def needs_approval(name: str) -> bool:
    """True for any MCP tool not marked read-only (unknown ones included)."""
    parts = split_name(name)
    if not parts:
        return False
    t = _tool(*parts)
    return not (t is not None and is_read_only(t))


def _coerce(args: Dict[str, Any], schema: Dict[str, Any]) -> Dict[str, Any]:
    """Small models send "10" for integers and "true" for booleans."""
    props = (schema or {}).get("properties") or {}
    out = dict(args or {})
    for k, v in list(out.items()):
        typ = (props.get(k) or {}).get("type")
        try:
            if typ == "integer" and isinstance(v, str):
                out[k] = int(float(v))
            elif typ == "number" and isinstance(v, str):
                out[k] = float(v)
            elif typ == "boolean" and isinstance(v, str):
                out[k] = v.strip().lower() in ("true", "1", "yes")
            elif typ == "array" and isinstance(v, str):
                out[k] = [x.strip() for x in v.split(",") if x.strip()]
        except ValueError:
            pass
    return out


def run(name: str, args: Dict[str, Any]) -> str:
    """Call an MCP tool for the model; always returns text."""
    parts = split_name(name)
    if not parts:
        return f"[MCP Error] unknown MCP tool {name!r}"
    server, tool = parts
    try:
        t = _tool(server, tool) or (manager().ensure(server) and _tool(server, tool))
        if t is None:
            return f"[MCP Error] {server} has no tool {tool!r}"
        props = ((getattr(t, "input_schema", {}) or {}).get("properties") or {})
        defaults = {k: v for k, v in (manager().servers[server].cfg.get("defaultArgs") or {}).items() if k in props}
        res = manager().call(server, tool, {**_coerce(args, getattr(t, "input_schema", {}) or {}), **defaults})
    except Exception as exc:
        return f"[MCP Error] {server}: {_reason(exc) if isinstance(exc, BaseException) else exc}"
    return render_result(res)


def render_result(res: Any) -> str:
    parts = []
    for c in getattr(res, "content", None) or []:
        kind = type(c).__name__
        if getattr(c, "text", None):
            parts.append(c.text)
        elif kind == "ImageContent":
            parts.append(f"[image: {getattr(c, 'mime_type', 'image')}]")
        elif kind == "EmbeddedResource":
            r = getattr(c, "resource", None)
            parts.append(getattr(r, "text", None) or f"[resource {getattr(r, 'uri', '')}]")
        elif kind == "ResourceLink":
            parts.append(f"[link {getattr(c, 'uri', '')}]")
    if not parts and getattr(res, "structured_content", None):
        parts.append(json.dumps(res.structured_content, ensure_ascii=False)[:20000])
    text = "\n".join(parts).strip() or "(no output)"
    return f"[MCP Error] {text}" if getattr(res, "is_error", False) else text


# ── Status for the UI ───────────────────────────────────────────────────────

def status(connect: bool = False) -> List[Dict[str, Any]]:
    """Every configured server with its state and tools. `connect` starts the
    enabled ones that aren't running (so the list shows their tools)."""
    out = []
    for name, cfg in load_config().items():
        enabled = cfg.get("enabled", True)
        s = manager().servers.get(name)
        if connect and enabled and (s is None or s.status in ("stopped",)):
            try:
                s = manager().ensure(name)
            except Exception:
                s = manager().servers.get(name)
        off = set(cfg.get("disabledTools") or [])
        tools = [{"name": t.name, "description": (t.description or "").strip().split("\n")[0][:160],
                  "read_only": is_read_only(t), "enabled": t.name not in off}
                 for t in (s.tools if s else [])]
        out.append({
            "name": name, "enabled": enabled,
            "status": (s.status if s else "stopped") if enabled else "off",
            "error": s.error if s else "",
            "transport": "http" if cfg.get("url") else "stdio",
            "command": cfg.get("url") or " ".join([str(cfg.get("command", ""))] + [str(a) for a in cfg.get("args") or []])[:200],
            "keywords": cfg.get("keywords") or [],
            "tools": tools,
        })
    return out
