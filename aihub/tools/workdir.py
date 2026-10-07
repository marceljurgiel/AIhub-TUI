"""
AIHub Tool support: working directory and environment facts.

Tools resolve relative paths against one working directory, first match wins:
a session override (the front-end's `/cd`), the configured `project_dir`, the
directory the user launched AIHub from (the OpenTUI front-end passes it as
AIHUB_WORKDIR, since its engine process runs inside the engine's own
checkout), else this process's cwd.

`environment_info()` tells the model where it is — without it, a request like
"save it on my desktop" leaves the model guessing a path.
"""
from __future__ import annotations

import os
import platform
import re
from datetime import datetime


# Set by `/cd` for the rest of the session; never persisted.
_session_dir = ""


def set_session_dir(path: str) -> str:
    """Switch the working directory for this session (`/cd`). A relative path
    is taken from the current working directory; "" drops the override.
    Returns the new effective working directory; raises if it isn't a dir."""
    global _session_dir
    if not path.strip():
        _session_dir = ""
        return workdir()
    target = resolve(path.strip())
    if not os.path.isdir(target):
        raise NotADirectoryError(f"not a directory: {target}")
    _session_dir = target
    return target


def workdir() -> str:
    """Directory that relative tool paths and shell commands run in."""
    from ..config import config

    for candidate in (_session_dir, config.project_dir, os.environ.get("AIHUB_WORKDIR", "")):
        if candidate:
            path = os.path.expanduser(candidate)
            if os.path.isdir(path):
                return os.path.abspath(path)
    return os.getcwd()


def resolve(path: str) -> str:
    """Absolute, normalised form of a tool path (~ expanded, relative paths
    taken from workdir())."""
    p = os.path.expanduser(str(path))
    if not os.path.isabs(p):
        p = os.path.join(workdir(), p)
    return os.path.normpath(p)


def user_dir(kind: str, fallback: str) -> str:
    """An XDG user directory (DESKTOP, DOCUMENTS, DOWNLOAD…) from
    ~/.config/user-dirs.dirs — localised systems name them e.g. ~/Pulpit."""
    home = os.path.expanduser("~")
    try:
        with open(os.path.join(home, ".config", "user-dirs.dirs"), encoding="utf-8") as f:
            for line in f:
                m = re.match(rf'\s*XDG_{kind}_DIR="(.*)"\s*$', line)
                if m:
                    return os.path.normpath(m.group(1).replace("$HOME", home))
    except OSError:
        pass
    return os.path.join(home, fallback)


def _os_name() -> str:
    try:
        with open("/etc/os-release", encoding="utf-8") as f:
            for line in f:
                if line.startswith("PRETTY_NAME="):
                    return line.split("=", 1)[1].strip().strip('"')
    except OSError:
        pass
    return f"{platform.system()} {platform.release()}".strip()


_ENV_HEADER = "Environment (the user's computer"


def environment_info() -> str:
    """Facts for the system prompt: OS, user folders, working directory, date."""
    home = os.path.expanduser("~")
    return (
        f"{_ENV_HEADER} — use these real paths; relative paths "
        "resolve against the working directory):\n"
        f"- OS: {_os_name()}\n"
        f"- Shell for run_terminal: {'PowerShell' if os.name == 'nt' else 'sh/bash'}\n"
        f"- Home directory: {home}\n"
        f"- Desktop: {user_dir('DESKTOP', 'Desktop')}\n"
        f"- Documents: {user_dir('DOCUMENTS', 'Documents')}\n"
        f"- Downloads: {user_dir('DOWNLOAD', 'Downloads')}\n"
        f"- Working directory: {workdir()}\n"
        f"- Today: {datetime.now():%Y-%m-%d}"
    )
