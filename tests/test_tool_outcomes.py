"""Tool failures and denials are reported as such — to the UI and the model."""
from __future__ import annotations

import pytest

from aihub import bridge
from aihub.chat import ToolCallResult, run_chat_turn, tool_failure
from aihub.memory import build_system_prompt
from aihub.tools import TOOLS_SCHEMA
from aihub.tools.file_ops import edit_file

from .conftest import SCHEMA, FakeBackend, text, tool_call


@pytest.mark.parametrize("result,expected", [
    ("[File OK] Written 5 bytes to: x", None),
    ("[Edit OK] Replaced 1 occurrence in x.", None),
    ("[Edit Error] File not found: /x.", "[Edit Error] File not found: /x."),
    ("[File Error] Could not write file: denied", "[File Error] Could not write file: denied"),
    ("[Tool Error] Unknown tool: 'x'", "[Tool Error] Unknown tool: 'x'"),
    ("[Search Error] No internet", "[Search Error] No internet"),
    ("$ ls\nfoo\n[Exit: 0]", None),
    ("$ false\n\n[Exit: 1]", "Command exited with 1"),
    ("$ sleep 9\n[Exit: TIMEOUT after 3s]", "Command exited with TIMEOUT after 3s"),
    ("$ x\n[Error: boom]", "Command failed: boom"),
    ("⚠ WARNING: rm\n$ rm x\n[Exit: 0]", None),
    # a file's *contents* mentioning an error tag is not a failure
    ("```\n[Edit Error] just a line in the file\n```", None),
    ("", None),
])
def test_tool_failure(result, expected):
    assert tool_failure(result) == expected


def _run_tool_turn(monkeypatch, result, approve=None):
    monkeypatch.setattr("aihub.chat.run_tool", lambda name, **kw: result)
    backend = FakeBackend([[tool_call({"name": "write_file", "args": {"path": "x"}})], [text("ok")]])
    events = list(run_chat_turn("m", [{"role": "user", "content": "hi"}], stream_fn=backend,
                                tools_schema=SCHEMA, approve_fn=approve))
    return next(e for e in events if isinstance(e, ToolCallResult))


def test_in_band_tool_error_sets_error(monkeypatch):
    r = _run_tool_turn(monkeypatch, "[File Error] Could not write file: read-only")
    assert r.error == "[File Error] Could not write file: read-only" and not r.denied


def test_success_has_no_error(monkeypatch):
    r = _run_tool_turn(monkeypatch, "[File OK] Written 3 bytes to: x")
    assert r.error is None and not r.denied


def test_denial_is_flagged_and_tells_the_model_plainly(monkeypatch):
    r = _run_tool_turn(monkeypatch, "unused", approve=lambda n, a: False)
    assert r.denied and r.error == "Denied by user"
    assert "NOT run" in r.result and "declined" in r.result


def test_bridge_forwards_denied(monkeypatch):
    out = []
    monkeypatch.setattr(bridge, "_emit", lambda rid, ev, data=None: out.append((ev, data)))
    bridge._emit_chat_event(1, ToolCallResult("c", "write_file", {}, "[Denied by user] …", 1, 0,
                                              error="Denied by user", denied=True))
    assert out == [("tool_result", {"call_id": "c", "name": "write_file", "arguments": {},
                                    "result": "[Denied by user] …", "duration_ms": 1, "round": 0,
                                    "error": "Denied by user", "denied": True})]


def test_edit_file_on_missing_file_points_to_write_file(tmp_path):
    out = edit_file(str(tmp_path / "new.txt"), "a", "b")
    assert out.startswith("[Edit Error] File not found") and "write_file" in out


def test_tool_descriptions_steer_new_files_to_write_file():
    desc = {t["function"]["name"]: t["function"]["description"] for t in TOOLS_SCHEMA}
    assert "cannot create files" in desc["edit_file"]
    assert "save or create a file" in desc["write_file"]
    assert "ALWAYS prefer edit_file" not in desc["write_file"]


def test_system_prompt_demands_truthful_tool_reports():
    prompt = build_system_prompt()
    assert "Report tool results truthfully" in prompt
    assert "security restrictions" in prompt
