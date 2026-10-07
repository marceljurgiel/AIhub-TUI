"""Connect Google: AIhub's own sign-in (loopback + PKCE) writes the token where
workspace-mcp reads it and installs Gmail, Calendar and Drive at once."""
import json
import os
import stat
import threading
from urllib.parse import parse_qs, urlparse

import pytest
import requests

from aihub import google_login as gl
from aihub import mcp_catalog, mcp_client

CLIENT = {"installed": {"client_id": "123-abc.apps.googleusercontent.com", "client_secret": "fake-secret",
                        "redirect_uris": ["http://localhost"]}}


class Resp:
    def __init__(self, data, status=200):
        self._d, self.status_code = data, status
        self.ok = status < 400
        self.content = json.dumps(data).encode()

    def json(self):
        return self._d

    def raise_for_status(self):
        if not self.ok:
            raise requests.HTTPError(str(self.status_code))


@pytest.fixture
def own_client(tmp_path, monkeypatch):
    """A user's own client in a fake Downloads folder, imported."""
    home = tmp_path / "home"
    (home / "Downloads").mkdir(parents=True)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.setattr(gl, "CONFIG_DIR", str(tmp_path / "aihub"))
    monkeypatch.setattr(mcp_client, "config_path", lambda: str(tmp_path / "aihub" / "mcp.json"))
    (home / "Downloads" / "client_secret_123.json").write_text(json.dumps(CLIENT))
    return home


def google(scope=" ".join(gl.SCOPES), sent=None):
    def post(url, data=None, params=None, timeout=None):
        if sent is not None:
            sent.append((url, data or params))
        if url == gl.TOKEN_URL:
            return Resp({"access_token": "at", "refresh_token": "rt", "expires_in": 3599, "scope": scope})
        return Resp({})

    def get(url, headers=None, timeout=None):
        assert headers == {"Authorization": "Bearer at"}
        return Resp({"email": "alex@example.com"})
    return post, get


def browser_that_signs_in(**extra):
    """Stands in for the user: follows the auth URL back to the loopback."""
    def open_browser(url):
        q = {k: v[0] for k, v in parse_qs(urlparse(url).query).items()}

        def go():
            params = {"state": q["state"], **({"code": "the-code"} if not extra else extra)}
            requests.get(q["redirect_uri"], params=params, timeout=5)
        threading.Thread(target=go, daemon=True).start()
        return True
    return open_browser


def test_auth_url_asks_offline_access_with_pkce_for_all_three():
    url = gl.auth_url("cid", "http://127.0.0.1:5555", "st", "ch")
    q = {k: v[0] for k, v in parse_qs(urlparse(url).query).items()}
    assert q["access_type"] == "offline" and q["prompt"] == "consent"
    assert q["code_challenge"] == "ch" and q["code_challenge_method"] == "S256"
    for s in ("gmail.modify", "calendar.events", "drive.file", "userinfo.email"):
        assert any(x.endswith(s) for x in q["scope"].split())


def test_import_finds_the_download_and_rejects_web_clients(own_client):
    out = gl.import_client()
    assert out["client_id"] == "123-abc.apps.googleusercontent.com"
    assert gl.own_client()["client_secret"] == "fake-secret"
    assert stat.S_IMODE(os.stat(gl.own_client_path()).st_mode) == 0o600 or os.name == "nt"
    web = own_client / "Downloads" / "client_secret_web.json"
    web.write_text(json.dumps({"web": CLIENT["installed"]}))
    with pytest.raises(ValueError, match="Desktop app"):
        gl.import_client(str(web))


def test_connect_signs_in_and_installs_three_servers(own_client, monkeypatch):
    gl.import_client()
    sent = []
    post, get = google(sent=sent)
    monkeypatch.setattr(gl.requests, "post", post)
    monkeypatch.setattr(gl.requests, "get", lambda *a, **k: get(*a, **k) if a[0] == gl.USERINFO_URL
                        else requests.Session().get(*a, **k))
    installed = []
    monkeypatch.setattr(mcp_catalog, "install_item", lambda i, v: installed.append((i, v)) or {"tools": 5})
    events = []
    out = gl.connect(threading.Event(), lambda e, d: events.append(e), open_browser=browser_that_signs_in(),
                     timeout=10)
    assert out["email"] == "alex@example.com" and out["services"] == ["gmail", "calendar", "drive"]
    assert [i for i, _ in installed] == ["gmail", "calendar", "drive"]
    assert installed[0][1]["email"] == "alex@example.com" and installed[0][1]["client_id"].startswith("123-")
    assert events[:2] == ["opening", "waiting"]
    token_call = next(d for u, d in sent if u == gl.TOKEN_URL)
    assert token_call["code"] == "the-code" and len(token_call["code_verifier"]) >= 43
    # The file workspace-mcp reads, private to the user.
    path = gl.credentials_path("alex@example.com")
    saved = json.load(open(path))
    assert saved["refresh_token"] == "rt" and saved["token_uri"] == gl.TOKEN_URL
    assert saved["client_secret"] == "fake-secret" and "expiry" in saved
    assert stat.S_IMODE(os.stat(path).st_mode) == 0o600 or os.name == "nt"


def test_unticked_services_are_left_out(own_client, monkeypatch):
    gl.import_client()
    only_mail = " ".join(gl.BASE_SCOPES + gl.SERVICE_SCOPES["gmail"])
    post, get = google(scope=only_mail)
    monkeypatch.setattr(gl.requests, "post", post)
    monkeypatch.setattr(gl.requests, "get", lambda *a, **k: get(*a, **k) if a[0] == gl.USERINFO_URL
                        else requests.Session().get(*a, **k))
    monkeypatch.setattr(mcp_catalog, "install_item", lambda i, v: {"tools": 1})
    out = gl.connect(threading.Event(), lambda e, d: None, open_browser=browser_that_signs_in(), timeout=10)
    assert out["services"] == ["gmail"] and out["missing"] == ["calendar", "drive"]


def test_saying_no_at_google_is_reported(own_client, monkeypatch):
    gl.import_client()
    with pytest.raises(PermissionError, match="didn't allow"):
        gl.connect(threading.Event(), lambda e, d: None,
                   open_browser=browser_that_signs_in(error="access_denied"), timeout=10)


def test_cancel_stops_waiting(own_client):
    gl.import_client()
    cancel = threading.Event()
    threading.Timer(0.3, cancel.set).start()
    with pytest.raises(InterruptedError):
        gl.connect(cancel, lambda e, d: None, open_browser=lambda url: False, timeout=10)


def test_without_any_client_the_user_is_sent_to_the_steps(tmp_path, monkeypatch):
    monkeypatch.setattr(gl, "CONFIG_DIR", str(tmp_path))
    monkeypatch.setattr(gl, "CLIENT_ID", "")
    with pytest.raises(LookupError, match="steps"):
        gl.client()


def test_disconnect_revokes_forgets_and_removes_the_servers(own_client, monkeypatch):
    path = gl.credentials_path("alex@example.com")
    gl._write_private(path, {"refresh_token": "rt"})
    ours = {"command": "workspace-mcp", "env": {"WORKSPACE_MCP_CREDENTIALS_DIR": gl.creds_dir()}}
    mcp_client.save_config({"gmail": ours, "drive": ours, "github": {"command": "gh"}})
    stopped, sent = [], []
    monkeypatch.setattr(mcp_client.manager(), "stop", stopped.append)
    monkeypatch.setattr(gl.requests, "post", lambda url, params=None, timeout=None: sent.append(params) or Resp({}))
    assert gl.status()["email"] == "alex@example.com"
    out = gl.disconnect()
    assert out == {"revoked": True, "removed": ["gmail", "drive"]}
    assert sent == [{"token": "rt"}] and not os.path.exists(path)
    assert set(mcp_client.load_config()) == {"github"}
    assert gl.status()["connected"] is False


def test_catalog_shows_one_google_item():
    items = {i["id"]: i for i in mcp_catalog.listing()}
    assert items["google"]["connect"] == "google"
    assert "gmail" not in items and "calendar" not in items and "drive" not in items
    with pytest.raises(ValueError, match="signing in"):
        mcp_catalog.install_item("google", {})
