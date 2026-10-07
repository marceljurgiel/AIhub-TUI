"""Online skill search (skills.sh + SkillsMP) and GitHub install — HTTP faked."""
import os
import shutil

import pytest

from aihub import bridge, skill_hub, skills


class Resp:
    def __init__(self, data=None, content=b"", status=200, text=""):
        self.data, self.content, self.status_code, self.text = data, content, status, text

    def json(self):
        return self.data

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


TREE = {"truncated": False, "tree": [
    {"path": "README.md", "type": "blob", "size": 10},
    {"path": "skills/pdf", "type": "tree"},
    {"path": "skills/pdf/SKILL.md", "type": "blob", "size": 80},
    {"path": "skills/pdf/scripts/fill.py", "type": "blob", "size": 20},
    {"path": "skills/pdf/forms.md", "type": "blob", "size": 5},
    {"path": "skills/docx/SKILL.md", "type": "blob", "size": 80},
]}
RAW = {
    "skills/pdf/SKILL.md": b"---\nname: pdf\ndescription: Work with PDF files. Use for PDFs.\n---\nRun scripts/fill.py.\n",
    "skills/pdf/scripts/fill.py": b"print('fill')\n",
    "skills/pdf/forms.md": b"# forms\n",
}


@pytest.fixture
def web(monkeypatch):
    calls = []

    def get(url, params=None, headers=None, timeout=None):
        calls.append(url)
        if url == skill_hub.SKILLS_SH:
            return Resp({"skills": [
                {"id": "anthropics/skills/pdf", "source": "anthropics/skills", "skillId": "pdf", "installs": 204741},
                {"id": "x", "source": "open.feishu.cn", "skillId": "lark-doc", "installs": 9},
            ]})
        if url == skill_hub.SKILLSMP:
            return Resp({"data": {"skills": [
                {"name": "pdf", "description": "Work with PDF files.", "stars": 5,
                 "githubUrl": "https://github.com/anthropics/skills/tree/main/skills/pdf"},
                {"name": "nano-pdf", "description": "Edit PDFs.", "stars": 9,
                 "githubUrl": "https://github.com/openclaw/openclaw/tree/main/skills/nano-pdf"},
            ]}})
        if "/git/trees/" in url:
            return Resp(TREE)
        if url.startswith("https://raw.githubusercontent.com/anthropics/skills/"):
            path = url.split("/", 6)[6]
            return Resp(content=RAW[path])
        return Resp(status=404)

    monkeypatch.setattr(skill_hub.requests, "get", get)
    skill_hub._cache.clear()
    shutil.rmtree(skills.user_dir(), ignore_errors=True)
    yield calls
    shutil.rmtree(skills.user_dir(), ignore_errors=True)


def test_search_merges_both_directories(web):
    out = skill_hub.search("pdf")
    rows = [(r["repo"], r["name"]) for r in out["results"]]
    assert rows == [("anthropics/skills", "pdf"), ("openclaw/openclaw", "nano-pdf")]   # no non-GitHub row
    pdf = out["results"][0]
    assert pdf["installs"] == 204741 and pdf["description"] == "Work with PDF files." and pdf["url"]
    assert out["errors"] == {}


def test_one_directory_failing_keeps_the_other(web, monkeypatch):
    real = skill_hub.requests.get
    monkeypatch.setattr(skill_hub.requests, "get", lambda url, **kw: Resp(status=429, text="rate limit")
                        if url == skill_hub.SKILLSMP else real(url, **kw))
    out = skill_hub.search("pdf")
    assert "SkillsMP" in out["errors"] and out["results"][0]["name"] == "pdf"


def test_search_is_cached(web):
    skill_hub.search("pdf")
    skill_hub.search("PDF")
    assert web.count(skill_hub.SKILLS_SH) == 1


def test_locate_by_name_or_url(web):
    loc = skill_hub.locate("anthropics/skills", "pdf")
    assert loc["folder"] == "skills/pdf" and len(loc["files"]) == 3
    assert skill_hub.locate("", url="https://github.com/anthropics/skills/tree/main/skills/pdf")["ref"] == "main"
    with pytest.raises(ValueError, match="no skill folder"):
        skill_hub.locate("anthropics/skills", "nope")


def test_preview_flags_scripts(web):
    p = skill_hub.preview("anthropics/skills", "pdf")
    assert p["name"] == "pdf" and p["body"] == "Run scripts/fill.py."
    assert p["scripts"] == ["scripts/fill.py"] and "forms.md" in p["files"]


def test_install_downloads_the_folder(web):
    sk = skill_hub.install("anthropics/skills", "pdf")
    folder = os.path.join(skills.user_dir(), "pdf")
    assert sk["name"] == "pdf" and sk["source"] == "user"
    assert open(os.path.join(folder, "scripts", "fill.py")).read() == "print('fill')\n"
    assert open(os.path.join(folder, ".source")).read().startswith("https://github.com/anthropics/skills/tree/HEAD/skills/pdf")
    skill_hub._cache.clear()
    assert skill_hub.search("pdf")["results"][0]["installed"] is True


def test_unsafe_paths_are_refused(web, monkeypatch):
    bad = {"truncated": False, "tree": [{"path": "s/SKILL.md", "type": "blob", "size": 1},
                                        {"path": "s/../../evil", "type": "blob", "size": 1}]}
    monkeypatch.setattr(skill_hub, "_tree", lambda repo, ref: bad["tree"])
    monkeypatch.setattr(skill_hub, "_raw", lambda *a: b"---\nname: s\ndescription: d\n---\nx")
    with pytest.raises(ValueError, match="unsafe path"):
        skill_hub.install("a/b", "s")


def test_bridge_handlers(web):
    assert bridge._h_skills_search({"query": "pdf"})["results"]
    assert bridge._h_skills_preview({"repo": "anthropics/skills", "name": "pdf"})["preview"]["name"] == "pdf"
    assert bridge._h_skills_install_remote({"repo": "anthropics/skills", "name": "pdf"})["skill"]["name"] == "pdf"
    with pytest.raises(ValueError):
        bridge._h_skills_search({"query": " "})
