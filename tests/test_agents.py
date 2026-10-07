"""Agent profiles: built-ins, user files, drafting, context size, turn setup."""
import os
import shutil

import pytest

from aihub import agents, bridge
from aihub.agents import AgentProfile
from aihub.target import Target

from .conftest import FakeBackend, text, tool_call


@pytest.fixture(autouse=True)
def clean_agents_dir():
    shutil.rmtree(agents.agents_dir(), ignore_errors=True)
    yield
    shutil.rmtree(agents.agents_dir(), ignore_errors=True)


def test_builtins_listed_first():
    names = [a.name for a in agents.list_agents()]
    assert names[:5] == ["coder", "researcher", "sysadmin", "writer", "mail"]
    assert agents.get_agent(None).name == "coder"


def test_save_parse_roundtrip_and_override():
    p = agents.save_agent(AgentProfile(name="Homeserver", description="server", prompt="You watch it.",
                                       tools=["run_terminal", "read_file"], permission="ask",
                                       model="qwen3:8b", context=12000))
    assert p.name == "homeserver" and os.path.exists(p.path)
    back = agents.get_agent("homeserver")
    assert back.tools == ["read_file", "run_terminal"] and back.model == "qwen3:8b"
    assert back.context == 12000 and back.prompt == "You watch it." and not back.builtin
    # A user file named like a built-in replaces it until deleted.
    agents.save_agent(AgentProfile(name="coder", prompt="Mine.", tools=["read_file"]))
    assert agents.get_agent("coder").prompt == "Mine."
    assert agents.delete_agent("coder")
    assert agents.get_agent("coder").builtin


def test_broken_file_is_skipped(caplog):
    os.makedirs(agents.agents_dir(), exist_ok=True)
    with open(os.path.join(agents.agents_dir(), "bad.md"), "w") as f:
        f.write("no front matter")
    assert "bad" not in [a.name for a in agents.list_agents()]


@pytest.mark.parametrize("prof,err", [
    (AgentProfile(name="Bad Name!", prompt="x"), "bad agent name"),
    (AgentProfile(name="x", prompt="x", tools=["rm_rf"]), "unknown tools"),
    (AgentProfile(name="x", prompt="x", permission="yolo"), "permission"),
    (AgentProfile(name="x", prompt="  "), "instructions"),
])
def test_validation(prof, err):
    with pytest.raises(ValueError, match=err):
        agents.validate(prof)


def test_draft_repairs_model_output():
    raw = ('Sure! ```json\n{"name": "Server Watcher", "description": "watches", '
           '"tools": ["run_terminal", "teleport"], "permission": "auto", "prompt": "You watch."}\n```')
    p = agents.draft_agent("watch my server", "m", complete=lambda msgs: raw)
    assert p.name == "server-watcher" and p.tools == ["run_terminal"]
    assert p.permission == "ask"            # shell access always asks


def test_draft_without_json_falls_back():
    p = agents.draft_agent("Sprawdzaj pogodę", "m", complete=lambda msgs: "I can't do JSON")
    assert p.name == "sprawdzaj-pogod" and "Sprawdzaj pogodę" in p.prompt
    assert set(p.tools) <= set(agents.READ_ONLY_TOOLS)


def test_kv_bytes_per_token():
    qwen3 = {"qwen3.block_count": 36, "qwen3.attention.head_count": 32,
             "qwen3.attention.head_count_kv": 8, "qwen3.attention.key_length": 128,
             "qwen3.attention.value_length": 128}
    assert agents.kv_bytes_per_token(qwen3) == 36 * 8 * 256 * 2
    # Hybrid model: per-layer kv heads unknown → conservative guess, not 0.
    lfm = {"lfm2moe.block_count": 24, "lfm2moe.attention.head_count": 32,
           "lfm2moe.attention.head_count_kv": None, "lfm2moe.attention.key_length": 64}
    assert agents.kv_bytes_per_token(lfm) == 24 * 8 * 128 * 2


class _Resp:
    def __init__(self, data): self.data = data
    def json(self): return self.data


def _ctx(monkeypatch, vram, size_gb, cap=0, max_ctx=40960):
    info = {"model_info": {"qwen3.block_count": 36, "qwen3.attention.head_count": 32,
                           "qwen3.attention.head_count_kv": 8, "qwen3.attention.key_length": 128}}
    monkeypatch.setattr("requests.post", lambda *a, **k: _Resp(info))
    monkeypatch.setattr("aihub.ollama_client.get_local_model_sizes", lambda: {"qwen3:8b": size_gb})
    monkeypatch.setattr("aihub.target.current",
                        lambda: Target("server", "s", vram, "learned", 0, 37, "measured", True))
    prof = AgentProfile(name="x", prompt="x", context=cap)
    return agents.agent_context("qwen3:8b", "ollama", prof, max_ctx)


def test_context_fits_next_to_the_model(monkeypatch):
    ctx, why = _ctx(monkeypatch, vram=8, size_gb=4.87)
    assert 12288 <= ctx <= 16384 and ctx % 2048 == 0 and "most that fits" in why
    assert _ctx(monkeypatch, vram=24, size_gb=4.87)[0] == 32768          # agent_default_context
    assert _ctx(monkeypatch, vram=24, size_gb=4.87, cap=12000)[0] == 12000
    assert _ctx(monkeypatch, vram=24, size_gb=4.87, max_ctx=16384)[0] == 16384
    ctx, why = _ctx(monkeypatch, vram=6, size_gb=4.87)
    assert ctx == agents.MIN_AGENT_CONTEXT and "CPU" in why


def test_tool_result_budget():
    assert agents.tool_result_budget(None) == 8000
    assert agents.tool_result_budget(2048) == 1500
    assert agents.tool_result_budget(8192) == 4915
    assert agents.tool_result_budget(32768) == 8000


# ── bridge ───────────────────────────────────────────────────────────────────

def _turn(monkeypatch, params, rounds):
    seen = {}

    def stream(model, messages, temperature, context_length=None, tools=None):
        seen.setdefault("system", messages[0]["content"])
        seen.setdefault("tools", [t["function"]["name"] for t in tools or []])
        return FakeBackend([rounds.pop(0)])(model, messages, temperature)

    events = []
    monkeypatch.setattr(bridge, "_resolve_stream_fn", lambda m, b: stream)
    monkeypatch.setattr(bridge, "_emit", lambda rid, ev, data=None: events.append((ev, data)))
    monkeypatch.setattr(bridge, "_done", lambda *a, **k: None)
    bridge._stream_chat_turn(1, {"model": "m", "agent": True, "messages": [{"role": "user", "content": "hi"}],
                                 **params})
    return seen, events


def test_turn_uses_the_agents_prompt_and_tools(monkeypatch):
    seen, _ = _turn(monkeypatch, {"agent_name": "researcher", "submode": "build"}, [[text("ok")]])
    assert "research agent" in seen["system"]
    assert "run_terminal" not in seen["tools"] and "search_web" in seen["tools"]


def test_ask_agent_asks_even_in_build(monkeypatch):
    monkeypatch.setattr("aihub.chat.run_tool", lambda name, **kw: "ran")
    q = []
    monkeypatch.setattr(bridge, "_perm_queues", type("Q", (dict,), {
        "__setitem__": lambda self, k, v: (q.append(v), v.put(False), dict.__setitem__(self, k, v))[-1]})())
    _, events = _turn(monkeypatch, {"agent_name": "sysadmin", "submode": "build"},
                      [[tool_call({"name": "run_terminal", "args": {"command": "ls"}})], [text("ok")]])
    assert any(ev == "permission_request" for ev, _ in events)


def test_auto_agent_runs_freely_in_build_but_asks_in_plan(monkeypatch):
    monkeypatch.setattr("aihub.chat.run_tool", lambda name, **kw: "ran")
    _, events = _turn(monkeypatch, {"agent_name": "coder", "submode": "build"},
                      [[tool_call({"name": "run_terminal", "args": {"command": "ls"}})], [text("ok")]])
    assert not any(ev == "permission_request" for ev, _ in events)
    assert agents.permission_policy(agents.get_agent("coder"), "plan") == "plan"


def test_unknown_agent_name_falls_back_to_coder(monkeypatch):
    seen, _ = _turn(monkeypatch, {"agent_name": "ghost"}, [[text("ok")]])
    assert "coding agent" in seen["system"]


def test_bridge_agents_crud_and_check(monkeypatch):
    saved = bridge._h_agents_save({"agent": {"name": "notes", "prompt": "Take notes.", "tools": ["read_file"]}})
    assert saved["agent"]["name"] == "notes"
    assert "notes" in [a["name"] for a in bridge._h_agents_list({})["agents"]]
    monkeypatch.setattr("aihub.agent.agent_capable", lambda m, b: (True, "", 40960))
    monkeypatch.setattr("aihub.agents.agent_context", lambda *a, **k: (14336, "most that fits"))
    out = bridge._h_agent_check({"model": "qwen3:8b", "agent": "notes"})
    assert out["ok"] and out["context"] == 14336 and out["agent"]["name"] == "notes"
    assert bridge._h_agent_check({"model": "m", "agent": "ghost"})["ok"] is False
    assert bridge._h_agents_delete({"name": "notes"})["deleted"]


def test_bridge_draft(monkeypatch):
    reply = '{"name": "pogoda", "tools": ["search_web"], "prompt": "You check weather."}'
    monkeypatch.setattr(bridge, "_resolve_stream_fn", lambda m, b: FakeBackend([[text(reply)]]))
    out = bridge._h_agents_draft({"description": "pogoda", "model": "m"})
    assert out["agent"]["name"] == "pogoda" and out["agent"]["tools"] == ["search_web"]


def test_tool_arguments_are_coerced():
    from aihub.tools import _fit_arguments
    from aihub.tools.web_search import search_web
    assert _fit_arguments(search_web, {"query": "x", "num_results": "10", "lang": "pl"}) == {"query": "x", "num_results": 10}
    assert _fit_arguments(search_web, {"query": 2026, "num_results": 3.0}) == {"query": "2026", "num_results": 3}
    assert _fit_arguments(search_web, {"query": "x", "num_results": "many"})["num_results"] == "many"


def test_missing_single_required_argument_is_built_from_the_others():
    from aihub.tools import _fit_arguments, run_tool
    from aihub.tools.web_search import search_web
    fixed = _fit_arguments(search_web, {"genre": "scifi or drama", "platforms": ["Netflix", "Apple TV"],
                                        "rating_restrictions": "none"})
    assert fixed == {"query": "scifi or drama Netflix Apple TV"}
    out = run_tool("read_file")                      # nothing to build from → a helpful error
    assert "It takes: path, max_lines (optional)" in out
