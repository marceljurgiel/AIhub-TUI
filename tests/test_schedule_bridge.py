"""Scheduled tasks over the bridge: the unattended turn and schedule.* handlers."""
from __future__ import annotations

import pytest

from aihub import agents, bridge
from aihub import schedule as sch

from .conftest import FakeBackend, text, tool_call


@pytest.fixture(autouse=True)
def clean(monkeypatch):
    import shutil
    shutil.rmtree(sch.schedule_dir(), ignore_errors=True)
    yield
    shutil.rmtree(sch.schedule_dir(), ignore_errors=True)
    agents.delete_agent("alex-ask")


@pytest.fixture
def tool_runs(monkeypatch):
    runs = []

    def fake_run_tool(name, **kwargs):
        runs.append((name, kwargs))
        return "tool output"

    monkeypatch.setattr("aihub.chat.run_tool", fake_run_tool)
    return runs


@pytest.fixture
def events(monkeypatch):
    out = []
    monkeypatch.setattr(bridge, "_emit", lambda req_id, event, data=None: out.append((event, data)))
    return out


def ask_agent():
    return agents.save_agent(agents.AgentProfile(
        name="alex-ask", prompt="You help alex.", tools=["run_terminal"], permission="ask"))


def test_unattended_turn_denies_ask_tools_without_asking(monkeypatch, tool_runs, events):
    ask_agent()
    backend = FakeBackend([
        [tool_call({"name": "run_terminal", "args": {"command": "ls"}})],
        [text("done")],
    ])
    monkeypatch.setattr(bridge, "_resolve_stream_fn", lambda m, b: backend)
    outcome = bridge._drive_turn(1, {
        "model": "m", "backend": "ollama", "agent": True, "agent_name": "alex-ask",
        "submode": "build", "tools_enabled": True,
        "messages": [{"role": "user", "content": "list files"}],
    }, unattended=True)
    names = [e for e, _ in events]
    assert "permission_request" not in names
    assert tool_runs == []
    [denied] = [d for e, d in events if e == "tool_result"]
    assert denied["name"] == "run_terminal" and denied["denied"] is True
    assert outcome.final_text == "done"
    assert outcome.cancelled is False and outcome.error == ""


# ── schedule.run and the oneshot handlers ─────────────────────────────────────

class Stream:
    """Captures what a streaming handler sent: events, done data, error."""

    def __init__(self, monkeypatch):
        self.events, self.done, self.error = [], None, None
        monkeypatch.setattr(bridge, "_emit", lambda r, e, d=None: self.events.append((e, d)))
        monkeypatch.setattr(bridge, "_done", lambda r, d=None: setattr(self, "done", d))
        monkeypatch.setattr(bridge, "_error", lambda r, m: setattr(self, "error", str(m)))


@pytest.fixture
def stream(monkeypatch):
    monkeypatch.setattr("aihub.agents.agent_context", lambda *a, **k: (8192, "test"))
    monkeypatch.setattr("aihub.ollama_client.is_ollama_running", lambda: True)
    return Stream(monkeypatch)


def use_backend(monkeypatch, backend):
    monkeypatch.setattr(bridge, "_resolve_stream_fn", lambda m, b: backend)


def task(name="digest", when="daily 08:00", agent="researcher"):
    return sch.save_task(sch.Task(name=name, agent=agent, model="llama3.2:3b", when=when,
                                  prompt="Say hello to alex.", created="2026-10-04T09:00:00"))


def history_files(model="llama3.2:3b"):
    import os
    from aihub.history import get_history_dir
    d = get_history_dir(model)
    return sorted(os.listdir(d)) if os.path.isdir(d) else []


def test_run_saves_history_even_with_autosave_off(monkeypatch, stream):
    from aihub.config import config
    monkeypatch.setattr(config, "history_autosave", False)
    task()
    before = history_files()
    use_backend(monkeypatch, FakeBackend([[text("Hello, alex!")]]))
    bridge._stream_schedule_run(7, {"name": "digest"})
    assert stream.error is None
    assert stream.done["status"] == "ok"
    assert stream.done["summary"] == "Hello, alex!"
    after = history_files()
    assert len(after) == len(before) + 1
    st = sch.load_state()["digest"]
    assert st["last_status"] == "ok" and st["last_summary"] == "Hello, alex!"
    assert st["last_session"] == {"model": "llama3.2:3b", "filename": stream.done["session"]["filename"]}
    assert stream.done["session"]["filename"] in after
    assert ("task", {"name": "digest", "phase": "started"}) in stream.events


def test_run_missing_agent_records_error(monkeypatch, stream):
    task()
    path = sch.get_task("digest").path
    with open(path, encoding="utf-8") as f:
        body = f.read().replace("agent: researcher", "agent: gone")
    with open(path, "w", encoding="utf-8") as f:
        f.write(body)
    bridge._stream_schedule_run(7, {"name": "digest"})
    assert stream.error == "agent 'gone' no longer exists — edit the task"
    st = sch.load_state()["digest"]
    assert st["last_status"] == "error" and st["last_error"] == stream.error


def test_run_backend_failure_records_error(monkeypatch, stream):
    task()

    def refused(*a, **k):
        raise ConnectionError("connection refused")

    use_backend(monkeypatch, refused)
    bridge._stream_schedule_run(7, {"name": "digest"})
    assert stream.error and "connection refused" in stream.error
    assert sch.load_state()["digest"]["last_status"] == "error"


def test_run_when_ollama_is_offline_does_not_start(monkeypatch, stream):
    task()
    monkeypatch.setattr("aihub.ollama_client.is_ollama_running", lambda: False)
    backend = FakeBackend([[text("never")]])
    use_backend(monkeypatch, backend)
    bridge._stream_schedule_run(7, {"name": "digest"})
    assert backend.calls == 0
    assert stream.error == "Ollama is offline — start it, then run the task again"
    assert sch.load_state()["digest"]["last_status"] == "error"


def test_run_same_slot_twice_is_skipped(monkeypatch, stream):
    task()
    backend = FakeBackend([[text("one")], [text("two")]])
    use_backend(monkeypatch, backend)
    bridge._stream_schedule_run(7, {"name": "digest", "slot": "2026-10-07T08:00:00"})
    assert stream.done["status"] == "ok"
    bridge._stream_schedule_run(8, {"name": "digest", "slot": "2026-10-07T08:00:00"})
    assert stream.done == {"status": "skipped", "summary": "already ran in another AIhub window",
                           "session": None}
    assert backend.calls == 1


def test_once_task_disabled_after_run(monkeypatch, stream):
    task(name="once", when="once 2026-10-07 09:00")
    use_backend(monkeypatch, FakeBackend([[text("ok")]]))
    bridge._stream_schedule_run(7, {"name": "once", "slot": "2026-10-07T09:00:00"})
    assert sch.get_task("once").enabled is False


def test_run_unknown_task(stream):
    bridge._stream_schedule_run(7, {"name": "nope"})
    assert stream.error == "no task named 'nope'"


def test_check_startup_reports_missed_and_resets_every(monkeypatch):
    from datetime import datetime
    task(name="daily")
    task(name="often", when="every 30m")

    class Now(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 10, 7, 10, 0)

    monkeypatch.setattr("aihub.schedule.datetime", Now)
    out = bridge._ONESHOT["schedule.check"]({"startup": True})
    assert out == {"due": [], "missed": [{"name": "daily", "when": "daily 08:00",
                                          "slot": "2026-10-07T08:00:00"}]}
    assert sch.load_state()["often"]["anchor"] == "2026-10-07T10:00:00"
    out = bridge._ONESHOT["schedule.check"]({"startup": False})
    assert out == {"due": [{"name": "daily", "slot": "2026-10-07T08:00:00"}], "missed": []}


def test_list_save_toggle_skip_delete_through_bridge():
    h = bridge._ONESHOT
    saved = h["schedule.save"]({"task": {"name": "digest", "agent": "researcher", "model": "m",
                                         "when": "Daily 8:00", "prompt": "Hi"}})["task"]
    assert saved["when"] == "daily 08:00"
    [row] = h["schedule.list"]({})["tasks"]
    assert row["name"] == "digest" and row["next_run"] and row["last_status"] is None
    assert h["schedule.toggle"]({"name": "digest", "enabled": False})["task"]["enabled"] is False
    assert h["schedule.list"]({})["tasks"][0]["next_run"] is None      # off: no next run
    assert h["schedule.skip"]({"name": "digest", "slot": "2026-10-07T08:00:00"}) == {"ok": True}
    assert h["schedule.delete"]({"name": "digest"}) == {"ok": True}
    assert h["schedule.list"]({})["tasks"] == []


def test_save_rejects_bad_when_through_bridge():
    with pytest.raises(ValueError, match="daily 08:00"):
        bridge._ONESHOT["schedule.save"]({"task": {"name": "x", "agent": "researcher",
                                                   "when": "tomorrow", "prompt": "Hi"}})


def test_run_session_is_dated_like_chat_sessions(monkeypatch, stream):
    """The app names chat sessions from a UTC timestamp (toISOString); a task's
    session must use the same clock, or History sorts it hours off."""
    import json
    import os
    from datetime import datetime, timezone
    from aihub.history import get_history_dir
    task()
    use_backend(monkeypatch, FakeBackend([[text("hi")]]))
    bridge._stream_schedule_run(7, {"name": "digest"})
    path = os.path.join(get_history_dir("llama3.2:3b"), stream.done["session"]["filename"])
    with open(path, encoding="utf-8") as f:
        start = datetime.fromisoformat(json.load(f)["start_time"])
    assert start.utcoffset() is not None and start.utcoffset().total_seconds() == 0
    assert abs((datetime.now(timezone.utc) - start).total_seconds()) < 60


def test_a_switched_off_task_waiting_in_the_queue_does_not_run(monkeypatch, stream):
    task()
    sch.set_enabled("digest", False)
    backend = FakeBackend([[text("never")]])
    use_backend(monkeypatch, backend)
    bridge._stream_schedule_run(7, {"name": "digest", "slot": "2026-10-07T08:00:00"})
    assert backend.calls == 0
    assert stream.done == {"status": "skipped", "summary": "switched off", "session": None}


def test_a_task_deleted_while_it_runs_leaves_no_state_behind(monkeypatch, stream):
    task()

    def stream_fn(*a, **k):
        sch.delete_task("digest")                  # the user deletes it mid-run
        return iter([text("done")])

    use_backend(monkeypatch, stream_fn)
    bridge._stream_schedule_run(7, {"name": "digest"})
    assert "digest" not in sch.load_state()
