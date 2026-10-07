"""
AIhub — Gmail (and the other Google services) through MCP.

The servers live in the catalog (aihub/mcp_catalog.py: gmail, calendar,
drive — all `workspace-mcp`, in its own venv). Connecting them is
aihub/google_login.py: one Google sign-in, done by AIhub, covers all three.

What's left here is the older path for scripts: pass an OAuth client's id
and secret and install Gmail with it; the server then asks for consent on
the first call.
"""
from __future__ import annotations

import re
from typing import Any, Dict


def check_google(v: Dict[str, str]) -> None:
    client_id = (v.get("client_id") or "").strip()
    secret = (v.get("client_secret") or "").strip()
    email = (v.get("email") or "").strip()
    if not re.fullmatch(r"[\w.-]+\.apps\.googleusercontent\.com", client_id):
        raise ValueError("the Client ID ends with .apps.googleusercontent.com — copy it from Google Cloud → Credentials")
    if len(secret) < 10:
        raise ValueError("paste the Client secret too (Google Cloud → Credentials → your Desktop client)")
    if email and "@" not in email:
        raise ValueError("that doesn't look like an email address")
    v["client_id"], v["client_secret"], v["email"] = client_id, secret, email


def setup(client_id: str, client_secret: str, email: str = "") -> Dict[str, Any]:
    from .mcp_catalog import install_item
    out = install_item("gmail", {"client_id": client_id, "client_secret": client_secret, "email": email})
    out["next"] = ("Ask AIhub about your mail (e.g. 'what's new in my inbox?'). The first time, "
                   "Gmail asks you to sign in: open the link it gives and allow access.")
    return out
