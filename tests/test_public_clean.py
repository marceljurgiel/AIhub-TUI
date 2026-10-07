"""The public repository must not carry anyone's personal data: real network
addresses, home folders, email addresses or credentials. Examples use the
documentation range 192.0.2.0/24, `gpu-box.lan`, the user `alex` and
placeholder emails."""
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SKIP_DIRS = {".git", "node_modules", ".venv", "venv", "__pycache__", ".pytest_cache", "build", "dist"}
SKIP_FILES = {"bun.lock", "test_public_clean.py"}
TEXT_EXT = {".py", ".ts", ".tsx", ".json", ".md", ".toml", ".yml", ".yaml", ".sh", ".ps1", ".txt",
            ".cfg", ".ini", ".html", ".tape", ".cmd"}

PATTERNS = {
    "private network address": re.compile(
        r"\b(?:10\.\d{1,3}|172\.(?:1[6-9]|2\d|3[01])|192\.168)\.\d{1,3}\.\d{1,3}\b"),
    "home folder": re.compile(r"/home/(?!alex\b|user\b|me\b|runner\b)[a-z][\w.-]*"
                              r"|[A-Z]:\\{1,2}Users\\{1,2}(?!alex\b|user\b|Public\b)[A-Za-z]"),
    "email address": re.compile(
        r"\b[\w.+-]+@(?!(?:example\.(?:com|org)|x\.pl|t\b|users\.noreply\.github\.com|anthropic\.com))"
        r"[\w-]+(?:\.[\w-]+)+\b"),
    "credential": re.compile(
        r"\bghp_[A-Za-z0-9]{36}\b|\bgithub_pat_\w{40,}|\bsk-(?:ant-)?[A-Za-z0-9_-]{40,}"
        r"|AIza[0-9A-Za-z_-]{35}|GOCSPX-[A-Za-z0-9_-]{28}|\bxox[abpr]-[A-Za-z0-9-]{20,}"
        r"|\bAKIA[0-9A-Z]{16}\b|-----BEGIN [A-Z ]*PRIVATE KEY-----"),
}
# Placeholder mailboxes used in examples and tests.
PLACEHOLDER_EMAILS = {"me@gmail.com", "you@gmail.com"}


def _files():
    """What can be published: tracked files plus untracked ones git wouldn't
    ignore (a developer's ignored local notes are not the repo's content)."""
    import subprocess
    try:
        out = subprocess.run(["git", "-C", ROOT, "ls-files", "--cached", "--others", "--exclude-standard"],
                             capture_output=True, text=True, check=True).stdout.split("\n")
    except (OSError, subprocess.CalledProcessError):
        out = None
    if out is not None:
        for rel in filter(None, out):
            if os.path.splitext(rel)[1] in TEXT_EXT and os.path.basename(rel) not in SKIP_FILES \
                    and os.path.exists(os.path.join(ROOT, rel)):
                yield os.path.join(ROOT, rel)
        return
    for dirpath, dirs, files in os.walk(ROOT):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS and not d.endswith(".egg-info")]
        for f in files:
            if f in SKIP_FILES or os.path.splitext(f)[1] not in TEXT_EXT:
                continue
            yield os.path.join(dirpath, f)


def test_no_personal_data_in_the_repository():
    hits = []
    for path in _files():
        with open(path, encoding="utf-8", errors="ignore") as fh:
            for n, line in enumerate(fh, 1):
                for what, pat in PATTERNS.items():
                    for m in pat.finditer(line):
                        if what == "email address" and m.group(0) in PLACEHOLDER_EMAILS:
                            continue
                        hits.append(f"{os.path.relpath(path, ROOT)}:{n}: {what}: {m.group(0)[:60]}")
    assert not hits, "personal data found:\n" + "\n".join(hits[:40])


def test_no_secrets_or_logs_are_tracked():
    bad = []
    for dirpath, dirs, files in os.walk(ROOT):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS and not d.endswith(".egg-info")]
        for f in files:
            if f in {".env", "id_rsa", "id_ed25519", "config.yaml", "mcp.json", "memory.md"} \
                    or f.endswith((".log", ".pem", ".key")):
                bad.append(os.path.relpath(os.path.join(dirpath, f), ROOT))
    assert not bad, f"files that look like private state: {bad}"
