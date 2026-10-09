"""
AIhub — "Connect Google": one sign-in for Gmail, Calendar and Drive.

AIhub runs Google's installed-app OAuth flow itself:
1. The browser opens Google's consent page.
2. A one-shot server on 127.0.0.1 receives the code.
3. The code is exchanged for tokens, using PKCE.

The result is written where the `workspace-mcp` servers read it:
`~/.aihub/mcp/google-credentials/{email}.json`, with `token`,
`refresh_token`, `token_uri`, `client_id`, `client_secret`, `scopes` and
`expiry`. In `--single-user` mode the servers pick it up and refresh it
themselves; they only ask again when scopes are missing, so one sign-in
covers all three services.

The OAuth client is either AIhub's own Google app (`CLIENT_ID` below, when
set) or the user's, imported from the client_secret_*.json that Google
Cloud downloads. A Desktop client's "secret" is not confidential; Google's
docs say installed apps can't keep one.
"""
from __future__ import annotations

import base64
import glob
import hashlib
import json
import logging
import os
import secrets
import threading
import time
import webbrowser
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any, Callable, Dict, List, Optional, Tuple
import re
from urllib.parse import parse_qs, quote, unquote, urlencode, urlparse

import requests

from .config import CONFIG_DIR

log = logging.getLogger(__name__)

# AIhub's own Google app. Empty until it exists — then "Connect Google" is
# one click; without it the user brings their own client (the wizard).
CLIENT_ID = ""
CLIENT_SECRET = ""

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
USERINFO_URL = "https://openidconnect.googleapis.com/v1/userinfo"
REVOKE_URL = "https://oauth2.googleapis.com/revoke"

_G = "https://www.googleapis.com/auth/"
BASE_SCOPES = [_G + "userinfo.email", _G + "userinfo.profile", "openid"]
# What workspace-mcp checks for each tool set; one consent asks for all.
SERVICE_SCOPES: Dict[str, List[str]] = {
    "gmail": [_G + s for s in ("gmail.readonly", "gmail.send", "gmail.compose", "gmail.modify",
                               "gmail.labels", "gmail.settings.basic")],
    "calendar": [_G + s for s in ("calendar", "calendar.readonly", "calendar.events")],
    "drive": [_G + s for s in ("drive", "drive.readonly", "drive.file")],
}
SERVICES = tuple(SERVICE_SCOPES)
SCOPES = BASE_SCOPES + [s for v in SERVICE_SCOPES.values() for s in v]

# The Google Cloud steps for "use my own Google app", with direct links.
OWN_APP_STEPS = [
    ("Create a project (any name)", "https://console.cloud.google.com/projectcreate"),
    ("Turn on Gmail, Calendar and Drive (one click on this page)",
     "https://console.cloud.google.com/flows/enableapi?apiid=gmail.googleapis.com,"
     "calendar-json.googleapis.com,drive.googleapis.com"),
    ("Consent screen: External, app name, your email → then Publish app (no weekly re-login)",
     "https://console.cloud.google.com/auth/branding"),
    ("Clients → Create client → Desktop app → Download JSON",
     "https://console.cloud.google.com/auth/clients/create"),
]


def creds_dir() -> str:
    return os.path.join(CONFIG_DIR, "mcp", "google-credentials")


def own_client_path() -> str:
    return os.path.join(CONFIG_DIR, "mcp", "google-client.json")


def builtin_available() -> bool:
    return bool(CLIENT_ID and CLIENT_SECRET)


# ── the OAuth client ─────────────────────────────────────────────────────────

def own_client() -> Optional[Dict[str, str]]:
    try:
        with open(own_client_path(), encoding="utf-8") as f:
            d = json.load(f)
        if d.get("client_id") and d.get("client_secret"):
            return {"client_id": d["client_id"], "client_secret": d["client_secret"]}
    except (OSError, ValueError):
        pass
    return None


def client(own: bool = False) -> Tuple[Dict[str, str], str]:
    """(client, "builtin"|"own"). The user's own client wins when asked for,
    or when AIhub has none of its own."""
    mine = own_client()
    if own or not builtin_available():
        if not mine:
            raise LookupError("no Google client yet — follow the steps to create one")
        return mine, "own"
    return {"client_id": CLIENT_ID, "client_secret": CLIENT_SECRET}, "builtin"


_CLIENT_ID = re.compile(r"[\w.-]+\.apps\.googleusercontent\.com")


def _read_client_json(path: str) -> Dict[str, str]:
    not_ours = ValueError(f"{os.path.basename(path)} is not a Google OAuth client file")
    with open(path, encoding="utf-8") as f:
        d = json.load(f)
    if not isinstance(d, dict):
        raise not_ours
    inner = d.get("installed") or d.get("web") or d
    cid = inner.get("client_id") if isinstance(inner, dict) else None
    sec = inner.get("client_secret") if isinstance(inner, dict) else None
    if not isinstance(cid, str) or not isinstance(sec, str) or not _CLIENT_ID.fullmatch(cid) or not sec:
        raise not_ours
    if "installed" not in d:
        raise ValueError("that client is not a Desktop app — create one of type 'Desktop app'")
    return {"client_id": cid, "client_secret": sec}


def downloads_dirs() -> List[str]:
    home = os.path.expanduser("~")
    dirs = [os.path.join(home, "Downloads")]
    try:   # localised folder names (Pobrane, Téléchargements…) on Linux
        with open(os.path.join(home, ".config", "user-dirs.dirs"), encoding="utf-8") as f:
            for line in f:
                if line.startswith("XDG_DOWNLOAD_DIR="):
                    dirs.insert(0, os.path.expandvars(line.split("=", 1)[1].strip().strip('"')))
    except OSError:
        pass
    return [d for d in dict.fromkeys(dirs) if os.path.isdir(d)]


def find_client_json(since: float = 0.0) -> Optional[str]:
    """The newest client_secret*.json in Downloads, newer than `since`."""
    found = []
    for d in downloads_dirs():
        for p in glob.glob(os.path.join(d, "client_secret*.json")):
            try:
                m = os.path.getmtime(p)
            except OSError:
                continue
            if m >= since:
                found.append((m, p))
    return max(found)[1] if found else None


def import_client(path: str = "") -> Dict[str, str]:
    """Adopt the user's own client: a given file, or the newest download."""
    path = os.path.expanduser(path.strip()) if path else (find_client_json() or "")
    if not path:
        raise FileNotFoundError("no client_secret….json in Downloads yet")
    c = _read_client_json(path)
    os.makedirs(os.path.dirname(own_client_path()), exist_ok=True)
    _write_private(own_client_path(), c)
    return {"client_id": c["client_id"], "path": path}


# ── the sign-in ──────────────────────────────────────────────────────────────

def _pkce() -> Tuple[str, str]:
    verifier = base64.urlsafe_b64encode(secrets.token_bytes(48)).decode().rstrip("=")
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    return verifier, challenge


def auth_url(client_id: str, redirect_uri: str, state: str, challenge: str) -> str:
    return AUTH_URL + "?" + urlencode({
        "client_id": client_id, "redirect_uri": redirect_uri, "response_type": "code",
        "scope": " ".join(SCOPES), "state": state, "access_type": "offline", "prompt": "consent",
        "include_granted_scopes": "true", "code_challenge": challenge, "code_challenge_method": "S256",
    })


# Shown before the code is exchanged and the servers installed: AIhub says
# how that went.
_DONE_PAGE = (b"<!doctype html><meta charset=utf-8><title>AIhub</title>"
              b"<body style='font-family:sans-serif;padding:3em'><h2>Signed in &mdash; finishing in AIhub&hellip;</h2>"
              b"<p>You can close this tab and go back to the terminal.</p>")


class Login:
    """One sign-in attempt: a loopback server and the PKCE pair."""

    # Seconds a connection may sit silent: a browser's speculative socket
    # must not block the loop (and with it Esc, the timeout and a paste).
    CONN_TIMEOUT = 5.0

    def __init__(self, own: bool = False):
        self.client, self.kind = client(own)
        self.verifier, challenge = _pkce()
        self.state = secrets.token_urlsafe(16)
        self.result: Dict[str, str] = {}
        login = self

        class Handler(BaseHTTPRequestHandler):
            timeout = login.CONN_TIMEOUT

            def do_GET(self):  # noqa: N802 (http.server API)
                q = {k: v[0] for k, v in parse_qs(urlparse(self.path).query).items()}
                if q.get("state") != login.state:
                    # Not this sign-in's answer (another local process, a
                    # guessed port): it can't end the sign-in; keep waiting.
                    self.send_response(400)
                    self.end_headers()
                    return
                if "code" in q or "error" in q:
                    login.result = q
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                self.wfile.write(_DONE_PAGE if "code" in q else b"<p>Sign-in did not finish - see AIhub.</p>")

            def log_message(self, *a):  # keep the terminal quiet
                pass

        self.server = HTTPServer(("127.0.0.1", 0), Handler)
        self.server.timeout = 0.5
        self.redirect_uri = f"http://127.0.0.1:{self.server.server_address[1]}"
        self.url = auth_url(self.client["client_id"], self.redirect_uri, self.state, challenge)

    def wait(self, cancel: threading.Event, timeout: float = 600) -> str:
        try:
            end = time.time() + timeout
            while not self.result and time.time() < end and not cancel.is_set():
                self.server.handle_request()
        finally:
            self.server.server_close()
        if cancel.is_set():
            raise InterruptedError("cancelled")
        return self.code_from(self.result)

    def code_from(self, q: Dict[str, str]) -> str:
        if not q:
            raise TimeoutError("no answer from Google — the sign-in page was closed or timed out")
        if q.get("state") != self.state:
            raise RuntimeError("the answer didn't match this sign-in (state) — try again")
        if q.get("error"):
            if q["error"] == "access_denied":
                raise PermissionError("you cancelled at Google, or didn't allow access")
            raise RuntimeError(f"Google said: {q['error']}")
        return q["code"]

    def finish_pasted(self, url: str) -> str:
        """Headless: the user signed in elsewhere and pasted the address the
        browser ended on (http://127.0.0.1:…/?code=…)."""
        q = {k: v[0] for k, v in parse_qs(urlparse(url.strip()).query).items()}
        return self.code_from(q)

    def exchange(self, code: str) -> Dict[str, Any]:
        r = requests.post(TOKEN_URL, data={
            "code": code, "client_id": self.client["client_id"], "client_secret": self.client["client_secret"],
            "redirect_uri": self.redirect_uri, "grant_type": "authorization_code", "code_verifier": self.verifier,
        }, timeout=30)
        d = r.json() if r.content else {}
        if not r.ok:
            raise RuntimeError(f"Google refused the sign-in: {d.get('error_description') or d.get('error') or r.status_code}")
        if not d.get("refresh_token"):
            raise RuntimeError("Google sent no refresh token — remove AIhub at myaccount.google.com/permissions and connect again")
        who = requests.get(USERINFO_URL, headers={"Authorization": f"Bearer {d['access_token']}"}, timeout=30)
        who.raise_for_status()
        d["email"] = who.json().get("email", "")
        if not d["email"]:
            raise RuntimeError("Google didn't say which account this is")
        return d


def granted_services(scope: str) -> List[str]:
    """Services whose scopes were all granted (Google lets people untick)."""
    have = set(scope.split())
    return [s for s, need in SERVICE_SCOPES.items() if set(need) <= have]


def credentials_path(email: str) -> str:
    return os.path.join(creds_dir(), quote(email, safe="@._-") + ".json")


def _private_dir(path: str) -> None:
    os.makedirs(path, mode=0o700, exist_ok=True)
    if os.name != "nt":
        os.chmod(path, 0o700)            # file names carry the account email


def _write_private(path: str, data: Dict[str, Any]) -> None:
    _private_dir(os.path.dirname(path))
    tmp = path + ".tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, path)


def save_credentials(tokens: Dict[str, Any], cl: Dict[str, str]) -> str:
    """Write the workspace-mcp credentials file; one account at a time (the
    servers run single-user and take the first file they find)."""
    _private_dir(creds_dir())
    expiry = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(seconds=int(tokens.get("expires_in", 3600)))
    path = credentials_path(tokens["email"])
    _write_private(path, {
        "token": tokens["access_token"], "refresh_token": tokens["refresh_token"], "token_uri": TOKEN_URL,
        "client_id": cl["client_id"], "client_secret": cl["client_secret"],
        "scopes": tokens.get("scope", " ".join(SCOPES)).split(), "expiry": expiry.isoformat(),
    })
    # Only once the new login is safely written does the old one go.
    for old in glob.glob(os.path.join(creds_dir(), "*.json")):
        if os.path.abspath(old) != os.path.abspath(path):
            os.remove(old)
    return path


def install_servers(email: str, cl: Dict[str, str], services: List[str],
                    progress: Callable[[str], None] = lambda s: None) -> Dict[str, int]:
    """The Gmail / Calendar / Drive servers, all on the one sign-in."""
    from .mcp_catalog import install_item
    tools = {}
    for s in services:
        progress(s)
        out = install_item(s, {"client_id": cl["client_id"], "client_secret": cl["client_secret"], "email": email})
        tools[s] = out.get("tools", 0)
    return tools


def connect(cancel: threading.Event, emit: Callable[[str, Dict[str, Any]], None], own: bool = False,
            open_browser: Callable[[str], bool] = webbrowser.open, timeout: float = 600) -> Dict[str, Any]:
    """The whole "Connect Google": browser → sign-in → servers ready."""
    login = Login(own)
    _pending["login"] = login
    try:
        opened = False
        try:
            opened = bool(open_browser(login.url))
        except Exception:
            opened = False
        emit("opening", {"url": login.url, "opened": opened, "client": login.kind})
        emit("waiting", {})
        code = login.wait(cancel, timeout)
        return finish(login, code, emit)
    finally:
        _pending.pop("login", None)


def finish(login: Login, code: str, emit: Callable[[str, Dict[str, Any]], None]) -> Dict[str, Any]:
    tokens = login.exchange(code)
    services = granted_services(tokens.get("scope", ""))
    if not services:
        _revoke(tokens.get("refresh_token", ""))      # don't leave a useless grant behind
        raise PermissionError("Google gave no access to Gmail, Calendar or Drive — connect again and tick the boxes")
    save_credentials(tokens, login.client)
    emit("installing", {"services": services})
    tools = install_servers(tokens["email"], login.client, services,
                            progress=lambda s: emit("installing", {"service": s}))
    missing = [s for s in SERVICES if s not in services]
    return {"email": tokens["email"], "services": services, "missing": missing, "tools": tools,
            "client": login.kind}


# A sign-in in progress, so a pasted redirect address can finish it.
_pending: Dict[str, Login] = {}


def finish_pasted(url: str, emit: Callable[[str, Dict[str, Any]], None]) -> Dict[str, Any]:
    login = _pending.get("login")
    if login is None:
        raise RuntimeError("no sign-in in progress — press Connect first")
    code = login.finish_pasted(url)
    login.result = {"code": code, "state": login.state}   # stops the waiting loop too
    return {"accepted": True}


# ── status / disconnect ──────────────────────────────────────────────────────

def _ours(entry: Dict[str, Any]) -> bool:
    return (entry.get("env") or {}).get("WORKSPACE_MCP_CREDENTIALS_DIR") == creds_dir()


def status() -> Dict[str, Any]:
    from .mcp_client import load_config
    files = sorted(glob.glob(os.path.join(creds_dir(), "*.json")))
    email = ""
    if files:
        try:
            with open(files[0], encoding="utf-8") as f:
                d = json.load(f)
            email = unquote(os.path.basename(files[0])[:-5])
            kind = "builtin" if d.get("client_id") == CLIENT_ID and CLIENT_ID else "own"
        except (OSError, ValueError):
            kind = ""
    cfg = load_config()
    services = [s for s in SERVICES if s in cfg and _ours(cfg[s])]
    return {"connected": bool(email), "email": email, "client": kind if email else "",
            "services": services, "builtin": builtin_available(), "own_client": own_client() is not None}


def _revoke(token: str) -> bool:
    """Revoke a token at Google. The token goes in the body, never the URL:
    a failed request's error text quotes the URL, and that gets logged."""
    if not token:
        return False
    try:
        return requests.post(REVOKE_URL, data={"token": token}, timeout=15).ok
    except Exception as exc:
        log.info("revoking the Google token failed (%s)", type(exc).__name__)
        return False


def disconnect() -> Dict[str, Any]:
    """Stop the three servers (so none refreshes the token meanwhile), revoke
    the token at Google, then forget it."""
    from .mcp_client import load_config, manager, save_config
    cfg = load_config()
    removed = [s for s in SERVICES if s in cfg and _ours(cfg[s])]
    for s in removed:
        manager().stop(s)
        cfg.pop(s)
    save_config(cfg)
    revoked = False
    for p in glob.glob(os.path.join(creds_dir(), "*.json")):
        try:
            with open(p, encoding="utf-8") as f:
                tok = json.load(f).get("refresh_token") or ""
        except (OSError, ValueError):
            tok = ""
        revoked = _revoke(tok) or revoked
        os.remove(p)                       # forgotten here either way
    return {"revoked": revoked, "removed": removed}
