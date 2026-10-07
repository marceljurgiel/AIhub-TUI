"""
AIHub — find and install skills from the internet.

Two public directories are searched together:

  skills.sh   (Vercel)  GET https://skills.sh/api/search?q=…
              ranked by installs; gives the GitHub repo + skill id, no description
  SkillsMP              GET https://skillsmp.com/api/v1/skills/search?q=…
              gives a description and the skill's GitHub folder link
              (anonymous: 50 searches a day, 10 a minute)

Skills live on GitHub. Previews and installs read just the skill's folder
through the GitHub API (repository tree + raw files) instead of cloning a
possibly huge repository. Installed skills land in ~/.aihub/skills/<name>.
"""
from __future__ import annotations

import logging
import os
import posixpath
import re
import shutil
import tempfile
import time
from typing import Any, Dict, List, Optional, Tuple

import requests

log = logging.getLogger(__name__)

SKILLS_SH = "https://skills.sh/api/search"
SKILLSMP = "https://skillsmp.com/api/v1/skills/search"
GH_TREE = "https://api.github.com/repos/{repo}/git/trees/{ref}?recursive=1"
GH_RAW = "https://raw.githubusercontent.com/{repo}/{ref}/{path}"
UA = {"User-Agent": "aihub"}

MAX_FILES = 60
MAX_BYTES = 8 * 1024 * 1024
CACHE_SECS = 600
_cache: Dict[str, Tuple[float, Any]] = {}
_REPO = re.compile(r"^[\w.-]+/[\w.-]+$")      # GitHub owner/repo (skills.sh lists others too)
_TREE_URL = re.compile(r"^https://github\.com/([^/]+/[^/]+)/tree/([^/]+)/(.+?)/?$")


def _cached(key: str, fn):
    hit = _cache.get(key)
    if hit and time.time() - hit[0] < CACHE_SECS:
        return hit[1]
    val = fn()
    _cache[key] = (time.time(), val)
    return val


def _get(url: str, **kw) -> requests.Response:
    headers = dict(UA)
    token = os.environ.get("GITHUB_TOKEN")
    if token and "api.github.com" in url:
        headers["Authorization"] = f"Bearer {token}"
    r = requests.get(url, headers=headers, timeout=kw.pop("timeout", 15), **kw)
    if r.status_code == 429 or (r.status_code == 403 and "rate limit" in r.text.lower()):
        raise RuntimeError(f"{url.split('/')[2]}: rate limit reached — try again later")
    r.raise_for_status()
    return r


# ── Search ───────────────────────────────────────────────────────────────────

def _search_skills_sh(q: str, limit: int) -> List[Dict[str, Any]]:
    data = _get(SKILLS_SH, params={"q": q, "limit": limit}).json()
    return [{
        "name": s.get("skillId") or s.get("name", ""),
        "repo": s.get("source", ""),
        "description": "",
        "installs": int(s.get("installs") or 0),
        "stars": 0,
        "url": "",
        "page": f"https://skills.sh/{s.get('id', '')}",
        "directory": "skills.sh",
    } for s in data.get("skills", []) if _REPO.match(s.get("source") or "")]


def _search_skillsmp(q: str, limit: int) -> List[Dict[str, Any]]:
    headers = {}
    key = os.environ.get("SKILLSMP_API_KEY")
    if key:
        headers["Authorization"] = f"Bearer {key}"
    data = requests.get(SKILLSMP, params={"q": q, "limit": limit}, headers={**UA, **headers}, timeout=15)
    if data.status_code == 429:
        raise RuntimeError("SkillsMP: daily search limit reached (50/day without a key)")
    data.raise_for_status()
    out = []
    for s in (data.json().get("data") or {}).get("skills", []):
        url = s.get("githubUrl") or ""
        m = _TREE_URL.match(url)
        out.append({
            "name": s.get("name", ""),
            "repo": m.group(1) if m else "",
            "description": " ".join(str(s.get("description") or "").split()),
            "installs": 0,
            "stars": int(s.get("stars") or 0),
            "url": url,
            "page": s.get("skillUrl", ""),
            "directory": "SkillsMP",
        })
    return [r for r in out if r["repo"]]


def search(query: str, limit: int = 25) -> Dict[str, Any]:
    """Both directories; one failing (rate limit, offline) doesn't hide the
    other. skills.sh results first (ranked by installs), then SkillsMP's
    that aren't duplicates; a duplicate lends its description and link."""
    q = query.strip()
    if not q:
        raise ValueError("type what the skill should do, e.g. 'pdf' or 'git commit'")
    results: Dict[str, List[Dict[str, Any]]] = {}
    errors: Dict[str, str] = {}
    for name, fn in (("skills.sh", _search_skills_sh), ("SkillsMP", _search_skillsmp)):
        try:
            results[name] = _cached(f"{name}:{q.lower()}:{limit}", lambda fn=fn: fn(q, limit))
        except Exception as exc:
            log.info("skill search on %s failed: %s", name, exc)
            errors[name] = str(exc)
    merged: List[Dict[str, Any]] = []
    index: Dict[Tuple[str, str], Dict[str, Any]] = {}
    for row in results.get("skills.sh", []) + results.get("SkillsMP", []):
        key = (row["repo"].lower(), row["name"].lower())
        if key in index:
            prev = index[key]
            prev["description"] = prev["description"] or row["description"]
            prev["url"] = prev["url"] or row["url"]
            prev["stars"] = prev["stars"] or row["stars"]
            continue
        index[key] = dict(row)
        merged.append(index[key])
    from .skills import list_skills
    have = {s.name for s in list_skills()}
    for r in merged:
        r["installed"] = r["name"].lower() in have
    return {"results": merged, "errors": errors}


# ── Locate a skill's folder on GitHub ───────────────────────────────────────

def _tree(repo: str, ref: str) -> List[Dict[str, Any]]:
    data = _cached(f"tree:{repo}:{ref}", lambda: _get(GH_TREE.format(repo=repo, ref=ref)).json())
    if data.get("truncated"):
        log.info("tree of %s is truncated — very large repository", repo)
    return data.get("tree") or []


def locate(repo: str, name: str = "", url: str = "") -> Dict[str, Any]:
    """{repo, ref, folder, files: [{path, size}]} for one skill. `url` is a
    GitHub folder link (SkillsMP); otherwise the folder holding a SKILL.md
    whose folder name is `name` (skills.sh ids are folder names)."""
    ref, folder = "HEAD", None
    m = _TREE_URL.match(url or "")
    if m:
        repo, ref, folder = m.group(1), m.group(2), m.group(3).strip("/")
    if not re.match(r"^[\w.-]+/[\w.-]+$", repo or ""):
        raise ValueError(f"not a GitHub repository: {repo!r}")
    tree = _tree(repo, ref)
    skill_dirs = [posixpath.dirname(t["path"]) for t in tree
                  if t.get("type") == "blob" and posixpath.basename(t["path"]) == "SKILL.md"]
    if folder is None:
        want = (name or "").lower()
        exact = [d for d in skill_dirs if posixpath.basename(d).lower() == want]
        if exact:
            folder = min(exact, key=len)
        elif len(skill_dirs) == 1:
            folder = skill_dirs[0]
        else:
            raise ValueError(f"no skill folder named {name!r} in {repo}")
    if folder not in skill_dirs:
        raise ValueError(f"{repo}/{folder} has no SKILL.md")
    prefix = folder + "/" if folder else ""
    nested = [d for d in skill_dirs if d != folder and d.startswith(prefix)]
    files = [{"path": t["path"], "size": int(t.get("size") or 0)} for t in tree
             if t.get("type") == "blob" and t["path"].startswith(prefix)
             and not any(t["path"].startswith(n + "/") for n in nested)]
    return {"repo": repo, "ref": ref, "folder": folder, "files": files}


def _raw(repo: str, ref: str, path: str) -> bytes:
    return _get(GH_RAW.format(repo=repo, ref=ref, path=path), timeout=30).content


def preview(repo: str, name: str = "", url: str = "") -> Dict[str, Any]:
    """The skill's SKILL.md and file list, before installing."""
    from .skills import parse_skill_md
    loc = locate(repo, name, url)
    md_path = posixpath.join(loc["folder"], "SKILL.md") if loc["folder"] else "SKILL.md"
    text = _raw(loc["repo"], loc["ref"], md_path).decode("utf-8", "replace")
    sk = parse_skill_md(text, loc["folder"] or loc["repo"].split("/")[1])
    prefix = loc["folder"] + "/" if loc["folder"] else ""
    others = [f["path"][len(prefix):] for f in loc["files"] if f["path"] != md_path]
    scripts = [f for f in others if f.endswith((".py", ".sh", ".js", ".ts", ".ps1", ".rb", ".pl"))]
    return {
        "name": sk.name, "description": sk.description, "body": sk.body,
        "repo": loc["repo"], "folder": loc["folder"], "files": others, "scripts": scripts,
        "size": sum(f["size"] for f in loc["files"]),
        "source_url": f"https://github.com/{loc['repo']}/tree/{loc['ref']}/{loc['folder']}".rstrip("/"),
    }


def install(repo: str, name: str = "", url: str = "") -> Dict[str, Any]:
    """Download the skill's folder into ~/.aihub/skills/<name>."""
    from .skills import get_skill, parse_skill_md, user_dir
    loc = locate(repo, name, url)
    files = loc["files"]
    if len(files) > MAX_FILES:
        raise ValueError(f"{len(files)} files — too many for one skill (max {MAX_FILES})")
    total = sum(f["size"] for f in files)
    if total > MAX_BYTES:
        raise ValueError(f"{total // 1024 // 1024} MB — too big for one skill")
    prefix = loc["folder"] + "/" if loc["folder"] else ""
    with tempfile.TemporaryDirectory(prefix="aihub-skill-") as tmp:
        for f in files:
            rel = f["path"][len(prefix):]
            dest = os.path.normpath(os.path.join(tmp, rel))
            if not dest.startswith(tmp + os.sep):
                raise ValueError(f"unsafe path in the skill: {rel}")
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            with open(dest, "wb") as out:
                out.write(_raw(loc["repo"], loc["ref"], f["path"]))
        with open(os.path.join(tmp, "SKILL.md"), encoding="utf-8") as fh:
            sk = parse_skill_md(fh.read(), tmp)
        target = os.path.join(user_dir(), sk.name)
        if os.path.exists(target):
            shutil.rmtree(target)
        os.makedirs(user_dir(), exist_ok=True)
        shutil.copytree(tmp, target)
    with open(os.path.join(target, ".source"), "w", encoding="utf-8") as fh:
        fh.write(f"https://github.com/{loc['repo']}/tree/{loc['ref']}/{loc['folder']}\n")
    return get_skill(sk.name).to_dict()
