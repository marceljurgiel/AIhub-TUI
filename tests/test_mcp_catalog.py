"""The one-click MCP catalog and import from Claude."""
import io
import json
import os
import sys
import tarfile

import pytest

from aihub import mcp_catalog as cat, mcp_client as m

SERVER = os.path.join(os.path.dirname(__file__), "fixtures", "mcp_test_server.py")


@pytest.fixture(autouse=True)
def clean():
    for p in (m.config_path(), os.path.expanduser("~/.claude.json")):
        try:
            os.remove(p)
        except FileNotFoundError:
            pass
    yield
    m.shutdown()
    m.manager().servers.clear()


def test_catalog_has_ten_entries_with_what_they_need():
    items = {i["id"]: i for i in cat.listing()}
    assert len(items) == 11 and {"github", "gmail", "calendar", "notion", "fetch", "playwright", "context7"} <= set(items)
    assert [f["key"] for f in items["github"]["fields"]] == ["token"]
    assert items["fetch"]["fields"] == [] and not items["gmail"]["installed"]


def test_builders_validate_and_produce_config(tmp_path, monkeypatch):
    monkeypatch.setattr(cat, "install_release", lambda repo, exe: f"/bin/{exe}")
    gh = cat.entry("github")["build"]({"token": "ghp_" + "x" * 36})
    assert gh["command"] == "/bin/github-mcp-server" and gh["env"]["GITHUB_PERSONAL_ACCESS_TOKEN"].startswith("ghp_")
    assert "--toolsets=repos,issues,pull_requests" in gh["args"]
    with pytest.raises(ValueError, match="GitHub token"):
        cat.entry("github")["build"]({"token": "short"})
    with pytest.raises(ValueError, match="no such folder"):
        cat.entry("obsidian")["build"]({"vault": str(tmp_path / "nope")})
    ha = cat.entry("homeassistant")["build"]({"url": "http://ha.local:8123/", "token": "abc"})
    assert ha == {**ha, "url": "http://ha.local:8123/api/mcp", "headers": {"Authorization": "Bearer abc"}}
    with pytest.raises(ValueError, match="Notion token"):
        cat.entry("notion")["build"]({})


def test_google_services_share_the_oauth_client(monkeypatch):
    monkeypatch.setattr(cat, "install_pip", lambda pkg, exe: f"/venv/{exe}")
    v = {"client_id": "1-a.apps.googleusercontent.com", "client_secret": "GOCSPX-123456", "email": "me@gmail.com"}
    gmail = cat.entry("gmail")["build"](dict(v))
    assert gmail["args"] == ["--tools", "gmail", "--single-user"] and gmail["defaultArgs"] == {"user_google_email": "me@gmail.com"}
    m.save_config({"gmail": gmail})
    cal = next(i for i in cat.listing() if i["id"] == "calendar")
    assert cal["prefill"] == v                                   # no second trip to Google Cloud
    with pytest.raises(ValueError, match="googleusercontent"):
        cat.entry("calendar")["build"]({"client_id": "x", "client_secret": "y" * 12})


def test_install_item_starts_the_server(monkeypatch):
    fake = {"id": "notes", "name": "Notes", "category": "test", "description": "test", "fields": [], "steps": [],
            "build": lambda v: {"command": sys.executable, "args": [SERVER], "keywords": ["note"]}}
    monkeypatch.setattr(cat, "CATALOG", cat.CATALOG + [fake])
    out = cat.install_item("notes", {})
    assert out == {"ok": True, "name": "notes", "tools": 4}
    assert next(i for i in cat.listing() if i["id"] == "notes")["installed"]


def test_install_release_picks_the_platform_build(monkeypatch, tmp_path):
    buf = io.BytesIO()
    data = b"#!/bin/sh\necho hi\n"
    asset = cat._platform_asset("github-mcp-server")
    if asset.endswith(".zip"):              # Windows builds ship as .zip with an .exe
        import zipfile
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr("github-mcp-server.exe", data)
    else:
        with tarfile.open(fileobj=buf, mode="w:gz") as tar:
            info = tarfile.TarInfo("github-mcp-server")
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))

    def fetch(url):
        if url.endswith("/releases/latest"):
            return json.dumps({"assets": [{"name": asset, "browser_download_url": "https://dl/x.tgz"}]}).encode()
        return buf.getvalue()
    path = cat.install_release("github/github-mcp-server", "github-mcp-server", fetch=fetch)
    assert os.access(path, os.X_OK) and open(path, "rb").read() == data
    assert asset.startswith("github-mcp-server_") and asset.endswith(".zip" if os.name == "nt" else ".tar.gz")


def test_import_from_claude():
    claude = {"mcpServers": {"obsidian": {"type": "stdio", "command": "ssh", "args": ["root@h", "npx", "x"], "env": {}}},
              "projects": {"/p": {"mcpServers": {"notes": {"command": sys.executable, "args": [SERVER]},
                                                  "broken": {"type": "stdio"}}}}}
    with open(os.path.expanduser("~/.claude.json"), "w") as f:
        json.dump(claude, f)
    assert sorted(cat.claude_servers()) == ["notes", "obsidian"]
    m.save_config({"notes": {"command": "x"}})
    out = cat.import_claude()
    assert out == {"added": ["obsidian"], "skipped": ["notes"]}
    assert m.load_config()["obsidian"] == {"command": "ssh", "args": ["root@h", "npx", "x"], "env": {}, "enabled": True}
