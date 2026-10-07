"""Skills: discovery, the model-facing catalog and tool, /skill, management."""
import os
import shutil
import subprocess

import pytest

from aihub import bridge, skills
from aihub.config import config
from aihub.tools import TOOLS_SCHEMA, wants_tools, without_unused

from .conftest import FakeBackend, text, tool_call


@pytest.fixture(autouse=True)
def clean(monkeypatch, tmp_path):
    shutil.rmtree(skills.user_dir(), ignore_errors=True)
    monkeypatch.setattr(config, "skills_disabled", [])
    monkeypatch.setattr(skills, "project_dir", lambda: str(tmp_path / "proj" / ".aihub" / "skills"))
    monkeypatch.setattr("aihub.config.save_config", lambda c: None)
    yield
    shutil.rmtree(skills.user_dir(), ignore_errors=True)


def _write(base, name, desc="Does a thing. Use when asked.", body="1. Do it.", extra=None):
    folder = os.path.join(base, name)
    os.makedirs(folder, exist_ok=True)
    with open(os.path.join(folder, "SKILL.md"), "w") as f:
        f.write(f"---\nname: {name}\ndescription: {desc}\n---\n{body}\n")
    for rel, content in (extra or {}).items():
        os.makedirs(os.path.dirname(os.path.join(folder, rel)), exist_ok=True)
        with open(os.path.join(folder, rel), "w") as f:
            f.write(content)
    return folder


def test_builtins_and_precedence(tmp_path):
    names = {s.name: s.source for s in skills.list_skills()}
    assert names["commit"] == "builtin" and names["code-review"] == "builtin"
    _write(skills.user_dir(), "commit", body="mine")
    assert skills.get_skill("commit").source == "user"
    _write(skills.project_dir(), "commit", body="project")
    sk = skills.get_skill("/commit")
    assert sk.source == "project" and sk.body == "project"


def test_parse_errors_and_skipping(caplog):
    with pytest.raises(ValueError, match="description"):
        skills.parse_skill_md("---\nname: x\n---\nbody")
    with pytest.raises(ValueError, match="front matter"):
        skills.parse_skill_md("just text")
    os.makedirs(os.path.join(skills.user_dir(), "broken"))
    open(os.path.join(skills.user_dir(), "broken", "SKILL.md"), "w").write("nope")
    assert "broken" not in [s.name for s in skills.list_skills()]


def test_catalog_lists_only_enabled():
    _write(skills.user_dir(), "pdf-tools", desc="Fill and merge PDF forms. Use for PDFs.")
    cat = skills.catalog_prompt()
    assert "call use_skill" in cat and "- pdf-tools: Fill and merge PDF forms" in cat
    config.skills_disabled = ["pdf-tools"]
    assert "pdf-tools" not in skills.catalog_prompt()


def test_use_skill_returns_body_and_files():
    folder = _write(skills.user_dir(), "report", body="Use template.md.", extra={"template.md": "# T", "scripts/run.sh": "echo"})
    out = skills.use_skill("report")
    assert out.startswith('<skill name="report">') and "Use template.md." in out
    assert os.path.join(folder, "template.md") in out and os.path.join(folder, "scripts", "run.sh") in out
    assert "No skill named 'nope'" in skills.use_skill("nope")
    config.skills_disabled = ["report"]
    assert "turned off" in skills.use_skill("report")


def test_long_body_is_truncated():
    _write(skills.user_dir(), "big", body="x" * 20000)
    assert len(skills.render_for_model(skills.get_skill("big"), 3000)) < 3200


def test_relevance_opens_tools_in_plain_chat():
    _write(skills.user_dir(), "invoice", desc="Create invoices for clients as PDF files. Use for invoicing.")
    assert wants_tools([{"role": "user", "content": "Make an invoice for my client Acme"}])
    assert wants_tools([{"role": "user", "content": "use invoice please"}])
    assert not wants_tools([{"role": "user", "content": "how are you today?"}])


def test_use_skill_tool_dropped_without_skills(monkeypatch):
    monkeypatch.setattr(skills, "BUILTIN_DIR", "/nonexistent")
    assert "use_skill" not in [t["function"]["name"] for t in without_unused(TOOLS_SCHEMA)]
    _write(skills.user_dir(), "one")
    assert "use_skill" in [t["function"]["name"] for t in without_unused(TOOLS_SCHEMA)]


def test_save_delete_enable():
    sk = skills.save_skill("Notes", "Keep meeting notes tidy. Use for notes.", "1. Tidy.")
    assert sk.name == "notes" and sk.source == "user"
    skills.set_enabled("notes", False)
    assert config.skills_disabled == ["notes"] and not skills.get_skill("notes").enabled
    skills.set_enabled("notes", True)
    assert config.skills_disabled == []
    assert skills.delete_skill("notes") and not skills.delete_skill("commit")   # built-in stays
    with pytest.raises(ValueError):
        skills.save_skill("x", "", "body")


@pytest.mark.skipif(not shutil.which("git"), reason="needs git")
def test_install_from_folder_and_git(tmp_path):
    src = tmp_path / "pack"
    _write(str(src / "skills"), "alpha", extra={"ref.md": "r"})
    _write(str(src / "skills"), "beta")
    got = skills.install(str(src))
    assert sorted(s.name for s in got) == ["alpha", "beta"]
    assert os.path.exists(os.path.join(skills.user_dir(), "alpha", "ref.md"))
    # A local git repo stands in for GitHub.
    repo = tmp_path / "repo"
    _write(str(repo), "gamma")
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run(["git", "-C", str(repo), "-c", "user.email=t@t", "-c", "user.name=t", "add", "."], check=True)
    subprocess.run(["git", "-C", str(repo), "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "x"], check=True)
    assert [s.name for s in skills.install(repo.as_uri())] == ["gamma"]
    with pytest.raises(ValueError, match="not a folder or a git URL"):
        skills.install("ftp://nope")
    (tmp_path / "empty").mkdir()
    with pytest.raises(ValueError, match="no SKILL.md"):
        skills.install(str(tmp_path / "empty"))


def test_github_tree_url_parsing():
    m = skills._GH_TREE.match("https://github.com/anthropics/skills/tree/main/skills/pdf")
    assert m.groups() == ("anthropics", "skills", "main", "skills/pdf")


def test_draft_skill():
    raw = '{"name": "Daily Standup", "description": "Write a standup note. Use when asked.", "instructions": "1. Ask."}'
    d = skills.draft_skill("standup", "m", complete=lambda msgs: raw)
    assert d == {"name": "daily-standup", "description": "Write a standup note. Use when asked.", "instructions": "1. Ask."}
    d = skills.draft_skill("Notatki ze spotkań", "m", complete=lambda msgs: "no json")
    assert d["name"] == "notatki-ze-spotka" and "Notatki ze spotkań" in d["instructions"]


# ── bridge ───────────────────────────────────────────────────────────────────

def _turn(monkeypatch, params, rounds, messages):
    seen = []

    def stream(model, msgs, temperature, context_length=None, tools=None):
        seen.append({"system": msgs[0]["content"], "tools": [t["function"]["name"] for t in tools or []]})
        return FakeBackend([rounds.pop(0)])(model, msgs, temperature)

    monkeypatch.setattr(bridge, "_resolve_stream_fn", lambda m, b: stream)
    monkeypatch.setattr(bridge, "_emit", lambda *a, **k: None)
    done = {}
    monkeypatch.setattr(bridge, "_done", lambda rid, data=None: done.update(data or {}))
    bridge._stream_chat_turn(1, {"model": "m", "messages": messages, **params})
    return seen, done


def test_chat_turn_offers_catalog_and_loads_a_skill(monkeypatch):
    _write(skills.user_dir(), "invoice", desc="Create invoices for clients. Use for invoicing.", body="SECRET-STEPS")
    seen, done = _turn(monkeypatch, {}, [
        [tool_call({"name": "use_skill", "args": {"skill": "invoice"}})], [text("done")]],
        [{"role": "system", "content": "x"}, {"role": "user", "content": "Make an invoice for a client"}])
    assert "- invoice: Create invoices" in seen[0]["system"] and "use_skill" in seen[0]["tools"]
    tool_msgs = [m for m in done["messages"] if m["role"] == "tool"]
    assert "SECRET-STEPS" in tool_msgs[0]["content"]


def test_plain_chitchat_gets_no_catalog(monkeypatch):
    seen, _ = _turn(monkeypatch, {}, [[text("hi")]],
                    [{"role": "system", "content": "x"}, {"role": "user", "content": "hello there"}])
    assert "# Skills" not in seen[0]["system"] and seen[0]["tools"] == []


def test_agents_always_get_use_skill(monkeypatch):
    seen, _ = _turn(monkeypatch, {"agent": True, "agent_name": "researcher"}, [[text("ok")]],
                    [{"role": "user", "content": "hi"}])
    assert "use_skill" in seen[0]["tools"] and "# Skills" in seen[0]["system"]


def test_bridge_invoke_and_crud(monkeypatch):
    out = bridge._h_skills_invoke({"name": "commit", "task": "only the message"})
    assert out["content"].startswith('Use the "commit" skill') and out["content"].endswith("Task: only the message")
    bridge._h_skills_save({"name": "n1", "description": "A thing. Use for things.", "instructions": "1."})
    assert "n1" in [s["name"] for s in bridge._h_skills_list({})["skills"]]
    assert bridge._h_skills_get({"name": "n1"})["skill"]["body"] == "1."
    bridge._h_skills_enable({"name": "n1", "enabled": False})
    assert config.skills_disabled == ["n1"]
    assert bridge._h_skills_delete({"name": "n1"})["deleted"]
    monkeypatch.setattr(bridge, "_resolve_stream_fn", lambda m, b: FakeBackend([[text(
        '{"name": "x1", "description": "d. Use when.", "instructions": "1."}')]]))
    assert bridge._h_skills_draft({"description": "x", "model": "m"})["draft"]["name"] == "x1"


def test_skill_called_as_a_tool_is_redirected(monkeypatch):
    _write(skills.user_dir(), "invoice", desc="Create invoices for clients. Use for invoicing.", body="STEPS")
    # As plain-text JSON (what llama3.2:3b did) and as a parsed tool call.
    for first in ([text('{"name": "invoice", "parameters": {"skill": "invoice"}}')],
                  [tool_call({"name": "invoice", "args": {}})]):
        _, done = _turn(monkeypatch, {}, [first, [text("ok")]],
                        [{"role": "system", "content": "x"}, {"role": "user", "content": "Make an invoice for a client"}])
        tool_msgs = [m for m in done["messages"] if m["role"] == "tool"]
        assert "STEPS" in tool_msgs[0]["content"]


def test_draft_steps_as_a_list_become_numbered_lines():
    raw = '{"name": "tv", "description": "TV picks. Use when asked.", "instructions": ["Ask the genre.", "Search the web."]}'
    d = skills.draft_skill("tv", "m", complete=lambda msgs: raw)
    assert d["instructions"] == "1. Ask the genre.\n2. Search the web."


def test_use_skill_twice_does_not_restart_it(monkeypatch):
    _write(skills.user_dir(), "invoice", desc="Create invoices for clients. Use for invoicing.", body="STEP ONE")
    history = [{"role": "system", "content": "x"},
               {"role": "user", "content": 'Use the "invoice" skill for this. <skill name="invoice">\nSTEP ONE\n</skill>\n\nTask: x'},
               {"role": "assistant", "content": "Which client?"},
               {"role": "user", "content": "Acme, make the invoice"}]
    _, done = _turn(monkeypatch, {}, [[tool_call({"name": "use_skill", "args": {"skill": "invoice"}})], [text("ok")]], history)
    tool_msgs = [m for m in done["messages"] if m["role"] == "tool"]
    assert tool_msgs[0]["content"].startswith("[Skill already loaded]")
