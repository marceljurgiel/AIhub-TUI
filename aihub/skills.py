"""
AIHub — skills: packaged instructions the model loads when a task needs them.

The format is Anthropic's Agent Skills (also used by Claude Code), so
existing skills install as-is: a folder with a SKILL.md —

    ---
    name: commit
    description: Write a commit message from the staged diff. Use when the user asks to commit.
    ---
    (instructions, loaded only when the skill is used)

plus any other files the instructions refer to (scripts, templates…).

Progressive disclosure keeps small context windows workable: the system
prompt lists only each skill's name and description; the model calls
`use_skill(name)` to load the instructions when a task matches. The user can
also invoke one directly (`/skill name task`), which sends the instructions
with the message — the reliable path for small models.

Where skills come from (a later one with the same name wins):
  built-in      aihub/data/skills/
  user          ~/.aihub/skills/<name>/SKILL.md
  project       <working dir>/.aihub/skills/<name>/SKILL.md
"""
from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional

import yaml

from .config import CONFIG_DIR

log = logging.getLogger(__name__)

_NAME = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
BUILTIN_DIR = os.path.join(os.path.dirname(__file__), "data", "skills")
MAX_DESCRIPTION = 200            # chars per skill in the catalog
MAX_CATALOG = 40                 # skills listed in the system prompt
MAX_FILES_LISTED = 20


def user_dir() -> str:
    return os.path.join(CONFIG_DIR, "skills")


def project_dir() -> Optional[str]:
    try:
        from .tools.workdir import workdir
        return os.path.join(workdir(), ".aihub", "skills")
    except Exception:
        return None


@dataclass
class Skill:
    name: str
    description: str
    body: str = ""
    path: str = ""                 # the skill's folder
    source: str = "user"           # builtin | user | project
    files: List[str] = field(default_factory=list)   # other files, relative
    enabled: bool = True

    def to_dict(self, with_body: bool = False) -> Dict[str, Any]:
        d = asdict(self)
        if not with_body:
            d.pop("body")
        return d


# ── Parsing ──────────────────────────────────────────────────────────────────

def parse_skill_md(text: str, folder: str = "") -> Skill:
    m = re.match(r"^﻿?---\s*\n(.*?)\n---\s*\n?(.*)$", text, re.DOTALL)
    if not m:
        raise ValueError("SKILL.md needs a --- front matter --- block with name and description")
    meta = yaml.safe_load(m.group(1)) or {}
    if not isinstance(meta, dict):
        raise ValueError("front matter must be key: value pairs")
    name = str(meta.get("name") or os.path.basename(folder.rstrip("/"))).strip().lower()
    desc = " ".join(str(meta.get("description") or "").split())
    if not _NAME.match(name):
        raise ValueError(f"bad skill name {name!r}: use a-z, 0-9, - or _")
    if not desc:
        raise ValueError("the skill needs a description (it's how the model knows when to use it)")
    return Skill(name=name, description=desc, body=m.group(2).strip(), path=folder)


def _other_files(folder: str) -> List[str]:
    out = []
    for root, dirs, files in os.walk(folder):
        dirs[:] = [d for d in dirs if not d.startswith(".")]
        for fn in sorted(files):
            rel = os.path.relpath(os.path.join(root, fn), folder)
            if rel != "SKILL.md" and not fn.startswith("."):
                out.append(rel)
            if len(out) >= MAX_FILES_LISTED:
                return out
    return out


def _scan(base: Optional[str], source: str) -> List[Skill]:
    if not base or not os.path.isdir(base):
        return []
    found = []
    for entry in sorted(os.listdir(base)):
        folder = os.path.join(base, entry)
        md = os.path.join(folder, "SKILL.md")
        if not os.path.isfile(md):
            continue
        try:
            with open(md, encoding="utf-8") as f:
                sk = parse_skill_md(f.read(), folder)
            sk.source, sk.files = source, _other_files(folder)
            found.append(sk)
        except Exception as exc:
            log.warning("skill %s skipped: %s", folder, exc)
    return found


def list_skills() -> List[Skill]:
    from .config import config
    disabled = set(getattr(config, "skills_disabled", None) or [])
    by_name: Dict[str, Skill] = {}
    for base, source in ((BUILTIN_DIR, "builtin"), (user_dir(), "user"), (project_dir(), "project")):
        for sk in _scan(base, source):
            by_name[sk.name] = sk
    out = sorted(by_name.values(), key=lambda s: (s.source != "project", s.source != "user", s.name))
    for sk in out:
        sk.enabled = sk.name not in disabled
    return out


def get_skill(name: str) -> Skill:
    name = (name or "").strip().lower().lstrip("/")
    for sk in list_skills():
        if sk.name == name:
            return sk
    raise KeyError(f"no skill named {name!r}")


def enabled_skills() -> List[Skill]:
    return [s for s in list_skills() if s.enabled]


# ── What the model sees ─────────────────────────────────────────────────────

def catalog_prompt(skills: Optional[List[Skill]] = None) -> str:
    """The system-prompt section listing skills (names + descriptions only)."""
    skills = enabled_skills() if skills is None else skills
    if not skills:
        return ""
    lines = [
        "# Skills",
        "Skills are saved instructions for specific tasks. When the user's request "
        "matches a skill's description, FIRST call use_skill with its name (skill=<name>), then "
        "follow the instructions it returns. Don't guess what a skill says.",
    ]
    for sk in skills[:MAX_CATALOG]:
        d = sk.description if len(sk.description) <= MAX_DESCRIPTION else sk.description[:MAX_DESCRIPTION - 1] + "…"
        lines.append(f"- {sk.name}: {d}")
    return "\n".join(lines)


def render_for_model(sk: Skill, budget: int = 8000) -> str:
    """Instructions as returned by use_skill / sent with /skill: the body,
    where its files are, capped to `budget` characters."""
    head = f'<skill name="{sk.name}">\n'
    tail = ""
    if sk.files:
        tail = (f"\n\nThis skill's folder is {sk.path}. Files in it (read with read_file, "
                f"run scripts with run_terminal if the instructions say so):\n"
                + "\n".join(f"- {os.path.join(sk.path, f)}" for f in sk.files))
    room = max(500, budget - len(head) - len(tail) - 20)
    body = sk.body if len(sk.body) <= room else sk.body[:room] + "\n… [instructions truncated]"
    return f"{head}{body}{tail}\n</skill>"


def use_skill(name: str) -> str:
    """Tool: load a skill's instructions."""
    try:
        sk = get_skill(name)
    except KeyError:
        names = ", ".join(s.name for s in enabled_skills()) or "none"
        return f"[Tool Error] No skill named '{name}'. Available skills: {names}"
    if not sk.enabled:
        return f"[Tool Error] The skill '{sk.name}' is turned off by the user."
    return render_for_model(sk)


_STOP = {"the", "a", "an", "and", "or", "to", "of", "in", "on", "for", "with", "when", "use",
         "this", "that", "it", "is", "are", "user", "asks", "from", "by", "as", "be", "your",
         "you", "my", "me", "i", "do", "if", "at", "any", "into", "about", "skill"}


def _words(text: str) -> set:
    return {w for w in re.findall(r"[a-ząćęłńóśźż0-9]{3,}", (text or "").lower()) if w not in _STOP}


def relevant(text: str, skills: Optional[List[Skill]] = None) -> List[Skill]:
    """Skills a message plausibly asks for: it names the skill, or shares two
    content words (prefix match, so "commits" ~ "commit") with its description.
    Decides whether plain chat offers tools this turn."""
    said = _words(text)
    if not said:
        return []
    hits = []
    for sk in enabled_skills() if skills is None else skills:
        if sk.name in (text or "").lower():
            hits.append(sk)
            continue
        desc = _words(sk.description)
        common = {w for w in said if any(w[:5] == d[:5] for d in desc)}
        if len(common) >= 2:
            hits.append(sk)
    return hits


# ── Managing ─────────────────────────────────────────────────────────────────

def set_enabled(name: str, enabled: bool) -> None:
    from .config import config, save_config
    get_skill(name)
    off = [n for n in (config.skills_disabled or []) if n != name]
    if not enabled:
        off.append(name)
    config.skills_disabled = sorted(set(off))
    save_config(config)


def render_skill_md(name: str, description: str, body: str) -> str:
    head = yaml.safe_dump({"name": name, "description": description}, sort_keys=False,
                          allow_unicode=True, width=10_000).strip()
    return f"---\n{head}\n---\n{body.strip()}\n"


def save_skill(name: str, description: str, body: str) -> Skill:
    """Create or replace a user skill."""
    text = render_skill_md(name.strip().lower(), description, body)
    sk = parse_skill_md(text)                 # validates
    if not sk.body:
        raise ValueError("the skill needs instructions")
    folder = os.path.join(user_dir(), sk.name)
    os.makedirs(folder, exist_ok=True)
    tmp = os.path.join(folder, ".SKILL.md.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(tmp, os.path.join(folder, "SKILL.md"))
    return get_skill(sk.name)


def delete_skill(name: str) -> bool:
    """Delete a user skill's folder (built-in and project skills stay)."""
    if not _NAME.match(name or ""):
        return False
    folder = os.path.join(user_dir(), name)
    if not os.path.isfile(os.path.join(folder, "SKILL.md")):
        return False
    shutil.rmtree(folder)
    return True


_GH_TREE = re.compile(r"^https://github\.com/([^/]+)/([^/]+)/tree/([^/]+)/(.+?)/?$")


def install(source: str) -> List[Skill]:
    """Install skills from a local folder or a git URL. A GitHub folder link
    (…/tree/<branch>/<path>) installs that one skill; a repo or folder with
    several skills installs each SKILL.md folder found (at most 30)."""
    source = source.strip()
    if not source:
        raise ValueError("give a folder path or a git URL")
    with tempfile.TemporaryDirectory(prefix="aihub-skill-") as tmp:
        if os.path.isdir(os.path.expanduser(source)):
            root = os.path.expanduser(source)
        else:
            sub = ""
            m = _GH_TREE.match(source)
            url, branch = source, None
            if m:
                owner, repo, branch, sub = m.groups()
                url = f"https://github.com/{owner}/{repo}.git"
            if not re.match(r"^(https://|git@|file://)", url):
                raise ValueError(f"not a folder or a git URL: {source}")
            cmd = ["git", "clone", "--depth", "1"] + (["--branch", branch] if branch else []) + [url, tmp + "/repo"]
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
            if r.returncode != 0:
                raise RuntimeError(f"git clone failed: {(r.stderr or r.stdout).strip()[-300:]}")
            root = os.path.join(tmp, "repo", sub)
            if not os.path.isdir(root):
                raise ValueError(f"{sub} not found in the repository")
        folders = []
        for dirpath, dirs, files in os.walk(root):
            dirs[:] = [d for d in dirs if not d.startswith(".")]
            if "SKILL.md" in files:
                folders.append(dirpath)
                dirs[:] = []                  # a skill's own subfolders aren't skills
        if not folders:
            raise ValueError("no SKILL.md found there")
        if len(folders) > 30:
            raise ValueError(f"{len(folders)} skills found — link one skill's folder instead")
        installed = []
        for folder in folders:
            with open(os.path.join(folder, "SKILL.md"), encoding="utf-8") as f:
                sk = parse_skill_md(f.read(), folder)
            dest = os.path.join(user_dir(), sk.name)
            if os.path.exists(dest):
                shutil.rmtree(dest)
            shutil.copytree(folder, dest, ignore=shutil.ignore_patterns(".git"))
            installed.append(sk.name)
    return [get_skill(n) for n in installed]


# ── Drafting a new skill from a description ─────────────────────────────────

DRAFT_PROMPT = """You write skills for AIHub, a local AI assistant. A skill is a short
set of instructions the assistant loads when a task matches.
From the user's description return ONLY a JSON object:
{"name": "short-lowercase-name", "description": "what it does + when to use it, one sentence",
 "instructions": "markdown instructions"}
The description is how the assistant decides to use the skill: say WHAT it
does and WHEN ("Use when the user asks to …").
The instructions: numbered steps in English, concrete (which tools to use:
read_file, list_files, search_files, search_web, edit_file, write_file,
run_terminal), what to check, the output format, what to avoid. Max 25 lines."""


def draft_skill(description: str, model: str, complete=None) -> Dict[str, str]:
    """A draft {name, description, instructions} for the user to review."""
    from .agents import _first_json, slugify
    if complete is None:
        from .ollama_client import chat_sync
        complete = lambda msgs: chat_sync(model, msgs, temperature=0.3, context_length=4096)  # noqa: E731
    raw = complete([{"role": "system", "content": DRAFT_PROMPT},
                    {"role": "user", "content": description.strip()}])
    try:
        data = _first_json(raw)
    except ValueError:
        log.info("skill draft: model answered without JSON: %r", (raw or "")[:200])
        data = {}
    raw_steps = data.get("instructions") or data.get("body") or ""
    if isinstance(raw_steps, list):          # models often return the steps as a list
        raw_steps = "\n".join(f"{i}. {str(step).strip()}" for i, step in enumerate(raw_steps, 1))
    instructions = str(raw_steps).strip() or (
        f"1. {description.strip()}\n2. Use your tools to check facts before answering.\n"
        "3. Answer briefly in the user's language.")
    desc = " ".join(str(data.get("description") or "").split()) or f"{description.strip()}"
    return {"name": slugify(str(data.get("name") or description)), "description": desc[:300],
            "instructions": instructions}
