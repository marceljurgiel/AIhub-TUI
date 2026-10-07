"""
AIHub — one-click MCP servers: a curated catalog of popular ones, plus
import from Claude Code / Claude Desktop.

Each catalog entry says how to install (npx; its own Python venv; a release
binary from GitHub; or a remote URL), which few values the user must give
(a token, a folder…) and builds the ~/.aihub/mcp.json entry from them —
with keywords (when the model gets its tools) and a trimmed tool set, since
small local models drown in long tool lists.
"""
from __future__ import annotations

import io
import json
import os
import platform
import shutil
import subprocess
import sys
import tarfile
from typing import Any, Callable, Dict, List, Optional

import requests

from .config import CONFIG_DIR

WORKSPACE_STEPS = [
    "console.cloud.google.com → create a project (any name)",
    "APIs & Services → Library → enable the {api}",
    "OAuth consent screen → External, Testing; add your Google address as a test user",
    "Credentials → Create credentials → OAuth client ID → Desktop app",
    "paste the Client ID and Client secret here (the same client works for Gmail, Calendar and Drive)",
]
GOOGLE_FIELDS = [
    {"key": "client_id", "label": "Google OAuth Client ID", "secret": False,
     "placeholder": "…apps.googleusercontent.com"},
    {"key": "client_secret", "label": "Client secret", "secret": True, "placeholder": "GOCSPX-…"},
    {"key": "email", "label": "Your Google address", "secret": False, "placeholder": "you@gmail.com"},
]


def _workspace(service: str, api: str, keywords: List[str], off: List[str]) -> Dict[str, Any]:
    def build(v: Dict[str, str]) -> Dict[str, Any]:
        from .mcp_gmail import check_google
        check_google(v)
        env = {"GOOGLE_OAUTH_CLIENT_ID": v["client_id"], "GOOGLE_OAUTH_CLIENT_SECRET": v["client_secret"],
               "OAUTHLIB_INSECURE_TRANSPORT": "1",
               "WORKSPACE_MCP_CREDENTIALS_DIR": os.path.join(CONFIG_DIR, "mcp", "google-credentials")}
        entry: Dict[str, Any] = {"command": install_pip("workspace-mcp", "workspace-mcp"),
                                 "args": ["--tools", service, "--single-user"], "env": env}
        if v.get("email"):
            env["USER_GOOGLE_EMAIL"] = v["email"]
            entry["defaultArgs"] = {"user_google_email": v["email"]}
        return {**entry, "keywords": keywords, "disabledTools": off}
    # Not listed on their own: "Google" (below) signs in once and installs
    # all three (aihub/google_login.py). Kept as entries for that, and for
    # installs made with the older paste-the-client form.
    return {"fields": GOOGLE_FIELDS, "steps": [s.format(api=api) for s in WORKSPACE_STEPS],
            "build": build, "shares": "google", "hidden": True}


def _github_build(v: Dict[str, str]) -> Dict[str, Any]:
    token = v.get("token", "").strip()
    if len(token) < 20:
        raise ValueError("paste a GitHub token (github.com/settings/tokens → fine-grained or classic)")
    return {"command": install_release("github/github-mcp-server", "github-mcp-server"),
            "args": ["stdio", "--toolsets=repos,issues,pull_requests"],
            "env": {"GITHUB_PERSONAL_ACCESS_TOKEN": token},
            "keywords": ["github", "repo", "pull request", "issue", "pr", "commit"]}


def _folder(v: Dict[str, str], key: str) -> str:
    p = os.path.expanduser(v.get(key, "").strip() or "~")
    if not os.path.isdir(p):
        raise ValueError(f"no such folder: {p}")
    return p


CATALOG: List[Dict[str, Any]] = [
    {"id": "github", "name": "GitHub", "category": "code",
     "description": "Repos, issues, pull requests — read, comment, open PRs",
     "fields": [{"key": "token", "label": "GitHub token", "secret": True, "placeholder": "github_pat_… or ghp_…"}],
     "steps": ["github.com/settings/tokens → Generate new token (fine-grained: pick repos, "
               "Contents/Issues/Pull requests read+write; or classic with 'repo')"],
     "build": _github_build},
    {"id": "google", "name": "Google", "category": "google",
     "description": "Gmail, Calendar and Drive — sign in with Google once",
     "fields": [], "steps": [], "connect": "google"},
    {"id": "gmail", "name": "Gmail", "category": "google",
     "description": "Search, read and summarise mail; drafts; send with your approval",
     **_workspace("gmail", "Gmail API",
                  ["mail", "gmail", "email", "e-mail", "inbox", "skrzynk", "poczt", "wiadomoś", "maila", "maili"],
                  ["get_gmail_messages_content_batch", "get_gmail_threads_content_batch",
                   "batch_modify_gmail_message_labels", "list_gmail_filters", "manage_gmail_filter",
                   "manage_gmail_label"])},
    {"id": "calendar", "name": "Google Calendar", "category": "google",
     "description": "Your events — what's next, find free time, add or move meetings",
     **_workspace("calendar", "Google Calendar API",
                  ["calendar", "kalendarz", "event", "wydarzen", "spotkani", "meeting", "termin", "schedule"], [])},
    {"id": "drive", "name": "Google Drive", "category": "google",
     "description": "Find and read your Drive files, Docs and Sheets",
     **_workspace("drive", "Google Drive API",
                  ["drive", "dysk", "gdrive", "google doc", "dokument google", "arkusz"], [])},
    {"id": "notion", "name": "Notion", "category": "notes",
     "description": "Search and read pages and databases; add pages",
     "fields": [{"key": "token", "label": "Notion integration token", "secret": True, "placeholder": "ntn_…"}],
     "steps": ["notion.so/profile/integrations → New integration → copy the Internal token",
               "in Notion, open each page/database AIhub may use → ••• → Connections → add your integration"],
     "build": lambda v: {"command": "npx", "args": ["-y", "@notionhq/notion-mcp-server"],
                         "env": {"NOTION_TOKEN": _need(v, "token", "the Notion token")},
                         "keywords": ["notion", "notatk", "note", "strona notion"]}},
    {"id": "obsidian", "name": "Obsidian", "category": "notes",
     "description": "Read, search and write notes in your Obsidian vault",
     "fields": [{"key": "vault", "label": "Vault folder", "secret": False, "placeholder": "~/Documents/Obsidian"}],
     "steps": ["give the folder of your vault (the one containing .obsidian/)"],
     "build": lambda v: {"command": "npx", "args": ["-y", "@mauricio.wolff/mcp-obsidian", _folder(v, "vault")],
                         "keywords": ["obsidian", "vault", "notatk", "notes"]}},
    {"id": "fetch", "name": "Fetch (web pages)", "category": "web",
     "description": "Read a web page as clean text — follow links the search finds",
     "fields": [], "steps": [],
     "build": lambda v: {"command": install_pip("mcp-server-fetch", "mcp-server-fetch"), "args": [],
                         "keywords": ["http", "www", "url", "link", "stron", "page", "artykuł", "article", "przeczytaj"]}},
    {"id": "git", "name": "Git", "category": "code",
     "description": "History, diffs, branches and commits of a local repository",
     "fields": [{"key": "repo", "label": "Repository folder", "secret": False, "placeholder": "~/projects/my-repo"}],
     "steps": [],
     "build": lambda v: {"command": install_pip("mcp-server-git", "mcp-server-git"),
                         "args": ["--repository", _folder(v, "repo")],
                         "keywords": ["git", "commit", "branch", "gałąź", "diff", "historia repo"]}},
    {"id": "playwright", "name": "Browser (Playwright)", "category": "web",
     "description": "Drive a real browser: open pages, click, fill forms, screenshots",
     "fields": [], "steps": ["uses your installed Chrome; runs headless"],
     "build": lambda v: {"command": "npx", "args": ["-y", "@playwright/mcp@latest", "--headless"],
                         "keywords": ["browser", "przeglądark", "kliknij", "click", "screenshot", "zrzut", "formularz", "playwright"]}},
    {"id": "context7", "name": "Context7 (library docs)", "category": "code",
     "description": "Up-to-date docs and examples for programming libraries",
     "fields": [], "steps": [],
     "build": lambda v: {"command": "npx", "args": ["-y", "@upstash/context7-mcp"],
                         "keywords": ["context7", "docs", "documentation", "dokumentacj", "library", "bibliotek", "api reference"]}},
    {"id": "homeassistant", "name": "Home Assistant", "category": "home",
     "description": "Control and ask about your smart home (lights, sensors, scenes)",
     "fields": [{"key": "url", "label": "Home Assistant URL", "secret": False, "placeholder": "http://homeassistant.local:8123"},
                {"key": "token", "label": "Long-lived access token", "secret": True, "placeholder": "eyJ…"}],
     "steps": ["Home Assistant → Settings → Devices & services → Add integration → Model Context Protocol Server",
               "your profile → Security → Long-lived access tokens → Create token"],
     "build": lambda v: {"url": _need(v, "url", "the Home Assistant URL").rstrip("/") + "/api/mcp",
                         "headers": {"Authorization": f"Bearer {_need(v, 'token', 'the access token')}"},
                         "keywords": ["home assistant", "światł", "light", "dom", "home", "czujnik", "sensor", "temperatur", "scen"]}},
]


def _need(v: Dict[str, str], key: str, what: str) -> str:
    val = (v.get(key) or "").strip()
    if not val:
        raise ValueError(f"enter {what}")
    return val


def entry(item_id: str) -> Dict[str, Any]:
    e = next((c for c in CATALOG if c["id"] == item_id), None)
    if e is None:
        raise KeyError(f"no catalog entry {item_id!r}")
    return e


def listing() -> List[Dict[str, Any]]:
    """For the UI: entries with installed flags and prefilled shared values."""
    from .mcp_client import load_config
    cfg = load_config()
    google = next((v for k, v in cfg.items() if "--tools" in (v.get("args") or []) and v.get("env", {}).get("GOOGLE_OAUTH_CLIENT_ID")), None)
    out = []
    for c in CATALOG:
        if c.get("hidden"):
            continue
        prefill = {}
        if c.get("shares") == "google" and google:
            prefill = {"client_id": google["env"].get("GOOGLE_OAUTH_CLIENT_ID", ""),
                       "client_secret": google["env"].get("GOOGLE_OAUTH_CLIENT_SECRET", ""),
                       "email": google["env"].get("USER_GOOGLE_EMAIL", "")}
        installed = c["id"] in cfg
        if c.get("connect") == "google":
            from .google_login import SERVICES
            installed = any(s in cfg for s in SERVICES)
        out.append({"id": c["id"], "name": c["name"], "category": c["category"], "description": c["description"],
                    "fields": c["fields"], "steps": c["steps"], "installed": installed, "prefill": prefill,
                    "connect": c.get("connect", "")})
    return out


def install_item(item_id: str, values: Dict[str, str]) -> Dict[str, Any]:
    """Install/configure a catalog server and start it. Returns tool count."""
    from . import mcp_client
    c = entry(item_id)
    if c.get("connect"):
        raise ValueError(f"{c['name']} connects by signing in, not with a form")
    built = c["build"]({k: str(v) for k, v in (values or {}).items()})
    built.setdefault("enabled", True)
    cfg = mcp_client.load_config()
    cfg[item_id] = built
    mcp_client.save_config(cfg)
    mcp_client.manager().stop(item_id)
    s = mcp_client.manager().ensure(item_id)
    return {"ok": True, "name": item_id, "tools": len(s.tools)}


# ── Installers ──────────────────────────────────────────────────────────────

def _base() -> str:
    return os.path.join(CONFIG_DIR, "mcp")


def install_pip(package: str, exe: str) -> str:
    """A Python MCP server in its own venv under ~/.aihub/mcp/venvs (no uv)."""
    venv = os.path.join(_base(), "venvs", package)
    bindir = os.path.join(venv, "Scripts" if os.name == "nt" else "bin")
    path = os.path.join(bindir, exe + (".exe" if os.name == "nt" else ""))
    if os.path.exists(path):
        return path
    os.makedirs(os.path.dirname(venv), exist_ok=True)
    subprocess.run([sys.executable, "-m", "venv", venv], check=True, capture_output=True, timeout=300)
    r = subprocess.run([os.path.join(bindir, "pip"), "install", "-q", "--upgrade", package],
                       capture_output=True, text=True, timeout=900)
    if r.returncode != 0 or not os.path.exists(path):
        shutil.rmtree(venv, ignore_errors=True)
        raise RuntimeError(f"installing {package} failed: {(r.stderr or r.stdout).strip()[-300:]}")
    return path


def _platform_asset(name: str) -> str:
    system = {"Linux": "Linux", "Darwin": "Darwin", "Windows": "Windows"}.get(platform.system(), platform.system())
    machine = platform.machine().lower()
    arch = {"x86_64": "x86_64", "amd64": "x86_64", "aarch64": "arm64", "arm64": "arm64", "i686": "i386"}.get(machine, machine)
    return f"{name}_{system}_{arch}." + ("zip" if system == "Windows" else "tar.gz")


def install_release(repo: str, exe: str, fetch: Optional[Callable[[str], bytes]] = None) -> str:
    """The latest release binary of a GitHub project, into ~/.aihub/mcp/bin."""
    target = os.path.join(_base(), "bin", exe + (".exe" if os.name == "nt" else ""))
    if os.path.exists(target):
        return target
    get = fetch or (lambda url: requests.get(url, timeout=120, headers={"User-Agent": "aihub"}).content)
    rel = json.loads(get(f"https://api.github.com/repos/{repo}/releases/latest"))
    want = _platform_asset(exe)
    asset = next((a for a in rel.get("assets", []) if a.get("name") == want), None)
    if not asset:
        raise RuntimeError(f"{repo} has no release build for this system ({want})")
    blob = get(asset["browser_download_url"])
    os.makedirs(os.path.dirname(target), exist_ok=True)
    wanted = {exe, exe + ".exe"}
    if want.endswith(".zip"):
        import zipfile
        with zipfile.ZipFile(io.BytesIO(blob)) as z:
            name = next((n for n in z.namelist() if os.path.basename(n) in wanted), None)
            if name is None:
                raise RuntimeError(f"{exe} not found in {want}")
            with z.open(name) as src, open(target + ".tmp", "wb") as dst:
                shutil.copyfileobj(src, dst)
    else:
        with tarfile.open(fileobj=io.BytesIO(blob), mode="r:gz") as tar:
            member = next((m for m in tar.getmembers() if os.path.basename(m.name) in wanted and m.isfile()), None)
            if member is None:
                raise RuntimeError(f"{exe} not found in {want}")
            with tar.extractfile(member) as src, open(target + ".tmp", "wb") as dst:
                shutil.copyfileobj(src, dst)
    os.chmod(target + ".tmp", 0o755)
    os.replace(target + ".tmp", target)
    return target


# ── Import from Claude ──────────────────────────────────────────────────────

def claude_sources() -> List[str]:
    home = os.path.expanduser("~")
    return [os.path.join(home, ".claude.json"),
            os.path.join(home, ".config", "Claude", "claude_desktop_config.json"),
            os.path.join(home, "Library", "Application Support", "Claude", "claude_desktop_config.json")]


def claude_servers() -> Dict[str, Dict[str, Any]]:
    """MCP servers configured for Claude Code (user scope + every project)
    and Claude Desktop. Later sources don't overwrite earlier names."""
    found: Dict[str, Dict[str, Any]] = {}

    def take(servers: Any) -> None:
        for name, cfg in (servers or {}).items() if isinstance(servers, dict) else []:
            if not isinstance(cfg, dict) or not (cfg.get("command") or cfg.get("url")):
                continue
            entry_ = {k: v for k, v in cfg.items() if k in ("command", "args", "env", "url", "headers", "cwd")}
            found.setdefault(name, entry_)
    for path in claude_sources():
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            continue
        take(data.get("mcpServers"))
        for proj in (data.get("projects") or {}).values():
            if isinstance(proj, dict):
                take(proj.get("mcpServers"))
    return found


def import_claude(names: Optional[List[str]] = None) -> Dict[str, Any]:
    """Add Claude's servers that AIhub doesn't have yet (enabled; they start
    when the MCP manager opens or a request mentions them)."""
    from . import mcp_client
    cfg = mcp_client.load_config()
    added, skipped = [], []
    for name, entry_ in claude_servers().items():
        if names and name not in names:
            continue
        key = mcp_client.safe_name(name)
        if key in cfg:
            skipped.append(key)
            continue
        cfg[key] = {**entry_, "enabled": True}
        added.append(key)
    mcp_client.save_config(cfg)
    return {"added": added, "skipped": skipped}
