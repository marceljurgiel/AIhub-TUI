"""Knowledge bases in a chat turn: excerpts in the system prompt, the
search_knowledge tool offered, and the history left without them."""
import pytest

from aihub import agents, bridge
from aihub import knowledge as kb

from .conftest import FakeBackend, text, tool_call
from .test_knowledge import fake_embed


@pytest.fixture
def home_base(tmp_path, monkeypatch):
    monkeypatch.setattr(kb, "CONFIG_DIR", str(tmp_path / "aihub"))
    monkeypatch.setattr(kb, "embed", fake_embed)
    kb._cache.clear()
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "boiler.md").write_text("# Boiler\n\nThe boiler pressure should stay between 1.2 and 1.8 bar.")
    kb.create("home", "House notes")
    kb.add("home", [str(docs)])
    return "home"


def _turn(monkeypatch, payload, rounds=None):
    seen, events, done = {"calls": []}, [], {}
    backend = FakeBackend(rounds or [[text("It should be 1.2–1.8 bar [1].")]])

    def stream(model, msgs, temperature, context_length=None, tools=None):
        seen["calls"].append({"system": msgs[0]["content"], "tools": [t["function"]["name"] for t in tools or []]})
        return backend(model, msgs, temperature)
    monkeypatch.setattr(bridge, "_resolve_stream_fn", lambda m, b: stream)
    monkeypatch.setattr(bridge, "_emit", lambda rid, e, d=None: events.append((e, d)))
    monkeypatch.setattr(bridge, "_done", lambda rid, d=None: done.update(d or {}))
    bridge._stream_chat_turn(1, {"model": "m", "tools_enabled": True, **payload})
    return seen, events, done


def test_kb_in_plain_chat_adds_excerpts_and_only_its_tool(monkeypatch, home_base):
    msgs = [{"role": "system", "content": "sys"}, {"role": "user", "content": "what boiler pressure is right?"}]
    seen, events, done = _turn(monkeypatch, {"messages": msgs, "knowledge": ["home"]})
    first = seen["calls"][0]
    assert "Excerpts from the user's knowledge base (home)" in first["system"] and "1.2 and 1.8 bar" in first["system"]
    assert first["tools"] == ["search_knowledge"]       # not every tool for a plain question
    assert ("knowledge", {"bases": ["home"], "hits": 1, "sources": ["docs/boiler.md"]}) in events
    assert done["messages"][0]["content"] == "sys"      # excerpts don't stay in the history


def test_the_model_can_search_deeper(monkeypatch, home_base):
    msgs = [{"role": "system", "content": "sys"}, {"role": "user", "content": "check my notes about the boiler"}]
    seen, events, done = _turn(monkeypatch, {"messages": msgs, "knowledge": ["home"]}, rounds=[
        [tool_call({"name": "search_knowledge", "args": {"query": "boiler pressure"}})],
        [text("1.2–1.8 bar [1].")],
    ])
    tool_msg = next(m for m in done["messages"] if m.get("role") == "tool")
    assert "[1] docs/boiler.md" in tool_msg["content"]
    assert not any(e == "permission_request" for e, _ in events)   # reading never asks


def test_agent_with_kb_entry(monkeypatch, home_base):
    p = agents.validate(agents.AgentProfile(name="house", prompt="You help with the house.",
                                            tools=["read_file", "kb:home", "kb:gone"], permission="ask"))
    assert p.tools == ["read_file", "kb:home", "kb:gone"]
    monkeypatch.setattr(agents, "get_agent", lambda name: p)
    monkeypatch.setattr("aihub.agents.get_agent", lambda name: p)
    msgs = [{"role": "system", "content": "sys"}, {"role": "user", "content": "boiler pressure?"}]
    seen, events, done = _turn(monkeypatch, {"messages": msgs, "agent": True, "agent_name": "house"})
    first = seen["calls"][0]
    assert first["system"].startswith("You help with the house.") and "1.2 and 1.8 bar" in first["system"]
    assert "search_knowledge" in first["tools"] and "read_file" in first["tools"]
    assert ("knowledge", {"bases": ["home"], "hits": 1, "sources": ["docs/boiler.md"]}) in events   # kb:gone skipped


def test_missing_embedder_is_reported_and_the_turn_still_answers(monkeypatch, home_base):
    def missing(texts, model=None):
        raise kb.EmbedderMissing("embeddinggemma isn't on http://192.0.2.10:11434 yet")
    monkeypatch.setattr(kb, "embed", missing)
    msgs = [{"role": "system", "content": "sys"}, {"role": "user", "content": "boiler?"}]
    seen, events, done = _turn(monkeypatch, {"messages": msgs, "knowledge": ["home"]})
    err = next(d for e, d in events if e == "knowledge")
    assert "download it" in err["error"] and seen["calls"]            # answered anyway


def test_bad_kb_names_in_agents_are_refused():
    with pytest.raises(ValueError, match="knowledge base name"):
        agents.validate(agents.AgentProfile(name="x", prompt="p", tools=["kb:Bad Name"]))
