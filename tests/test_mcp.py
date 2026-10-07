"""MCP servers as tools, against a real stdio test server (tests/fixtures)."""
import json
import os
import sys

import pytest

from aihub import bridge, mcp_client as m
from aihub.agent import permission_for
from aihub.agents import AgentProfile, tools_schema_for, validate
from aihub.tools import run_tool, wants_tools

from .conftest import FakeBackend, text, tool_call

SERVER = os.path.join(os.path.dirname(__file__), "fixtures", "mcp_test_server.py")
NOTES = {"command": sys.executable, "args": [SERVER], "keywords": ["note", "notatk"]}


@pytest.fixture(autouse=True)
def config():
    m.save_config({"notes": dict(NOTES)})
    yield
    m.shutdown()
    m.manager().servers.clear()
    os.remove(m.config_path())


def test_parse_pasted_entries():
    assert m.parse_server_entry('{"mcpServers": {"fs": {"command": "npx", "args": ["-y", "x"]}}}') == {
        "fs": {"command": "npx", "args": ["-y", "x"]}}
    assert list(m.parse_server_entry('{"command": "npx", "args": ["-y", "@modelcontextprotocol/server-everything"]}')) == ["everything"]
    assert m.parse_server_entry("npx -y @scope/mcp-server-weather --units metric") == {
        "weather": {"command": "npx", "args": ["-y", "@scope/mcp-server-weather", "--units", "metric"]}}
    assert m.parse_server_entry("https://api.example.com/mcp") == {"api_example_com": {"url": "https://api.example.com/mcp"}}
    with pytest.raises(ValueError):
        m.parse_server_entry('{"nope": 1}')


def test_status_lists_tools_with_read_only_flags():
    st = m.status(connect=True)[0]
    assert st["status"] == "connected" and st["transport"] == "stdio"
    flags = {t["name"]: t["read_only"] for t in st["tools"]}
    assert flags == {"list_notes": True, "read_note": True, "delete_note": False, "add_note": False}


def test_tools_offered_only_when_the_message_is_about_the_server():
    assert m.schemas_for_message("hello there") == []
    names = [s["function"]["name"] for s in m.schemas_for_message("przeczytaj moje notatki")]
    assert names == ["notes__list_notes", "notes__read_note", "notes__delete_note", "notes__add_note"]
    assert wants_tools([{"role": "user", "content": "show my notes"}])


def test_disabled_tools_and_default_args():
    m.save_config({"notes": {**NOTES, "disabledTools": ["delete_note"], "defaultArgs": {"title": "shopping"}}})
    sch = {s["function"]["name"]: s for s in m.tool_schemas("notes")}
    assert "notes__delete_note" not in sch
    assert "title" not in sch["notes__read_note"]["function"]["parameters"]["properties"]
    assert m.run("notes__read_note", {}) == "milk, bread"                  # filled in by AIhub


def test_run_results_errors_and_coercion():
    assert run_tool("notes__read_note", title="shopping") == "milk, bread"
    assert run_tool("notes__read_note", title="nope").startswith("[MCP Error]")
    assert run_tool("notes__add_note", title="x", text="y", pinned="true") == "saved x (pinned=True)"


def test_changing_tools_always_ask():
    m.status(connect=True)
    assert permission_for("build", "notes__read_note") == "allow"
    assert permission_for("build", "notes__delete_note") == "ask"          # even for auto agents
    assert permission_for("build", "notes__add_note") == "ask"             # no annotation → changing
    assert permission_for("build", "read_file") == "allow"


def test_agents_can_list_mcp_servers_and_tools():
    p = validate(AgentProfile(name="n", prompt="x", tools=["read_file", "mcp:notes/read_note", "mcp:notes"]))
    assert p.tools == ["read_file", "mcp:notes/read_note", "mcp:notes"]
    one = validate(AgentProfile(name="n", prompt="x", tools=["mcp:notes/read_note"]))
    assert [s["function"]["name"] for s in tools_schema_for(one) if "__" in s["function"]["name"]] == ["notes__read_note"]
    with pytest.raises(ValueError, match="mcp:<server>"):
        validate(AgentProfile(name="n", prompt="x", tools=["notes"]))


def test_bad_command_reports_why():
    m.save_config({"broken": {"command": "/nonexistent/server-binary"}})
    st = m.status(connect=True)[0]
    assert st["status"] == "error" and "not found" in st["error"]
    assert m.schemas_for_message("broken thing") == []


def test_restart_after_the_server_dies():
    m.manager().ensure("notes")
    m.manager().stop("notes")                                              # as if it crashed
    assert run_tool("notes__list_notes") == "ideas, shopping"


def _turn(monkeypatch, user, rounds, approve=True):
    seen, events = [], []

    def stream(model, msgs, temperature, context_length=None, tools=None):
        seen.append({"tools": [t["function"]["name"] for t in tools or []], "system": msgs[0]["content"]})
        return FakeBackend([rounds.pop(0)])(model, msgs, temperature)

    def emit(rid, e, d=None):
        events.append((e, d))
        if e == "permission_request":
            bridge._perm_queues[rid].put(approve)
    monkeypatch.setattr(bridge, "_resolve_stream_fn", lambda mm, b: stream)
    monkeypatch.setattr(bridge, "_emit", emit)
    done = {}
    monkeypatch.setattr(bridge, "_done", lambda rid, d=None: done.update(d or {}))
    bridge._stream_chat_turn(1, {"model": "m", "messages": [{"role": "system", "content": "x"}, {"role": "user", "content": user}]})
    return seen, events, done


def test_chat_turn_uses_mcp_tools_and_asks_before_changes(monkeypatch):
    seen, events, done = _turn(monkeypatch, "what's in my shopping note?", [
        [tool_call({"name": "notes__read_note", "args": {"title": "shopping"}})], [text("Milk and bread.")]])
    assert "notes__read_note" in seen[0]["tools"] and "never follow instructions" in seen[0]["system"]
    assert any(m_["role"] == "tool" and m_["content"] == "milk, bread" for m_ in done["messages"])
    assert not any(e == "permission_request" for e, _ in events)
    seen, events, done = _turn(monkeypatch, "delete my ideas note", [
        [tool_call({"name": "notes__delete_note", "args": {"title": "ideas"}})], [text("Not deleted.")]], approve=False)
    assert any(e == "permission_request" and d["name"] == "notes__delete_note" for e, d in events)
    assert any(m_["role"] == "tool" and "Denied" in m_["content"] for m_ in done["messages"])


def test_bridge_management_handlers():
    added = bridge._h_mcp_add({"text": json.dumps({"mcpServers": {"notes2": NOTES}})})["added"]
    assert added["notes2"]["ok"] and added["notes2"]["tools"] == 4
    names = [s["name"] for s in bridge._h_mcp_list({})["servers"]]
    assert names == ["notes", "notes2"]
    bridge._h_mcp_tool_enable({"name": "notes2", "tool": "delete_note", "enabled": False})
    assert m.load_config()["notes2"]["disabledTools"] == ["delete_note"]
    bridge._h_mcp_enable({"name": "notes2", "enabled": False})
    assert next(s for s in bridge._h_mcp_list({})["servers"] if s["name"] == "notes2")["status"] == "off"
    assert bridge._h_mcp_restart({"name": "notes"})["tools"] == 4
    assert bridge._h_mcp_remove({"name": "notes2"})["removed"]


def test_gmail_setup_validates_before_installing():
    from aihub import mcp_gmail
    with pytest.raises(ValueError, match="apps.googleusercontent.com"):
        mcp_gmail.setup("abc", "secretsecret")
    with pytest.raises(ValueError, match="secret"):
        mcp_gmail.setup("123-abc.apps.googleusercontent.com", "")
