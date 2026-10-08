"""Scheduled tasks: when they run (pure schedule math) and how they're stored."""
from __future__ import annotations

from datetime import datetime as dt

import pytest

from aihub.schedule import latest_slot, next_run, parse_when


# ── Schedule math ─────────────────────────────────────────────────────────────

@pytest.mark.parametrize("text,kind", [
    ("every 15m", "every"), ("every 2h", "every"), ("daily 08:00", "daily"),
    ("weekdays 7:30", "weekdays"), ("weekly mon 09:00", "weekly"),
    ("once 2026-10-08 10:00", "once"), ("  Daily   08:00 ", "daily"),
])
def test_parse_accepts(text, kind):
    assert parse_when(text).kind == kind


def test_parse_canonical_text():
    assert parse_when("  Daily   8:00 ").text == "daily 08:00"
    assert parse_when("weekly mon 9:05").text == "weekly Mon 09:05"
    assert parse_when("EVERY 2H").text == "every 2h"


@pytest.mark.parametrize("bad", [
    "", "every 4m", "every 0h", "daily 25:00", "daily 08:60", "weekly Xyz 08:00",
    "0 8 * * *", "once 2026-13-01 10:00", "tomorrow",
])
def test_parse_rejects_with_examples(bad):
    with pytest.raises(ValueError, match="daily 08:00"):
        parse_when(bad)


def test_daily_before_and_after_slot():
    w = parse_when("daily 08:00")
    assert next_run(w, dt(2026, 10, 7, 7, 59)) == dt(2026, 10, 7, 8, 0)
    assert next_run(w, dt(2026, 10, 7, 8, 0)) == dt(2026, 10, 8, 8, 0)


def test_weekdays_friday_evening_goes_to_monday():   # 2026-10-09 is a Friday
    assert next_run(parse_when("weekdays 08:00"), dt(2026, 10, 9, 20, 0)) == dt(2026, 10, 12, 8, 0)


def test_weekly_crosses_week_boundary():              # 2026-10-11 is a Sunday
    assert next_run(parse_when("weekly Mon 09:00"), dt(2026, 10, 11, 10, 0)) == dt(2026, 10, 12, 9, 0)


def test_once_in_future_and_past():
    w = parse_when("once 2026-10-08 10:00")
    assert next_run(w, dt(2026, 10, 7)) == dt(2026, 10, 8, 10, 0)
    assert next_run(parse_when("once 2026-10-01 10:00"), dt(2026, 10, 7)) is None


def test_every_adds_the_interval():
    assert next_run(parse_when("every 2h"), dt(2026, 10, 7, 8, 0)) == dt(2026, 10, 7, 10, 0)


def test_dst_day_keeps_wall_clock():                  # EU DST ends 2026-10-25
    assert next_run(parse_when("daily 08:00"), dt(2026, 10, 25, 9, 0)) == dt(2026, 10, 26, 8, 0)


def test_latest_slot_returns_only_the_last_one():
    w = parse_when("daily 08:00")
    assert latest_slot(w, dt(2026, 10, 4, 9, 0), dt(2026, 10, 7, 10, 0)) == dt(2026, 10, 7, 8, 0)
    assert latest_slot(w, dt(2026, 10, 7, 8, 0), dt(2026, 10, 7, 10, 0)) is None


def test_latest_slot_every():
    w = parse_when("every 30m")
    assert latest_slot(w, dt(2026, 10, 7, 8, 0), dt(2026, 10, 7, 9, 10)) == dt(2026, 10, 7, 9, 0)
    assert latest_slot(w, dt(2026, 10, 7, 8, 0), dt(2026, 10, 7, 8, 20)) is None


def test_latest_slot_after_a_year_is_fast_and_right():
    w = parse_when("weekdays 08:00")
    # 2026-10-07 is a Wednesday.
    assert latest_slot(w, dt(2025, 1, 1), dt(2026, 10, 7, 9, 0)) == dt(2026, 10, 7, 8, 0)


def test_latest_slot_once_missed_long_ago_is_still_found():
    w = parse_when("once 2026-09-01 10:00")
    assert latest_slot(w, dt(2026, 8, 1), dt(2026, 10, 7)) == dt(2026, 9, 1, 10, 0)
    assert latest_slot(w, dt(2026, 9, 1, 10, 0), dt(2026, 10, 7)) is None


# ── Task files and run state ──────────────────────────────────────────────────

import json  # noqa: E402
import os  # noqa: E402

from aihub import schedule as sch  # noqa: E402


@pytest.fixture(autouse=True)
def clean_schedule_dir():
    import shutil
    shutil.rmtree(sch.schedule_dir(), ignore_errors=True)
    yield
    shutil.rmtree(sch.schedule_dir(), ignore_errors=True)


def make(name="digest", when="daily 08:00", created="2026-10-04T09:00:00", **kw):
    t = sch.Task(name=name, agent=kw.pop("agent", "researcher"), model="llama3.2:3b",
                 when=when, prompt=kw.pop("prompt", "Say hello."), created=created, **kw)
    return sch.save_task(t)


PROMPT = 'Line 1\n---\nkey: "value"\n  indented: yes'


def test_save_and_list_round_trip():
    saved = sch.save_task(sch.Task(name="digest", agent="researcher", model="llama3.2:3b",
                                   when="Daily 8:00", prompt=PROMPT))
    assert saved.when == "daily 08:00"
    assert saved.created
    [t] = sch.list_tasks()
    assert (t.name, t.agent, t.model, t.when, t.prompt, t.enabled, t.broken) == \
        ("digest", "researcher", "llama3.2:3b", "daily 08:00", PROMPT, True, "")
    assert sch.get_task("digest").prompt == PROMPT


@pytest.mark.parametrize("kw,msg", [
    ({"when": "tomorrow"}, "daily 08:00"),
    ({"name": "Bad Name!"}, "bad task name"),
    ({"agent": "gone"}, "no agent named 'gone'"),
    ({"prompt": "  "}, "needs a prompt"),
])
def test_save_rejects(kw, msg):
    with pytest.raises(ValueError, match=msg):
        make(**kw)


def test_save_refuses_to_overwrite_another_task():
    make()
    with pytest.raises(ValueError, match="a task named 'digest' already exists"):
        sch.save_task(sch.Task(name="digest", agent="researcher", when="daily 09:00", prompt="x"))
    # Saving the same task again (an edit) is fine.
    sch.save_task(sch.Task(name="digest", agent="researcher", when="daily 09:00", prompt="x"),
                  original_name="digest")
    assert sch.get_task("digest").when == "daily 09:00"


def test_get_missing_task():
    with pytest.raises(KeyError, match="no task named 'nope'"):
        sch.get_task("nope")


def test_rename_moves_state():
    make(name="a")
    sch.update_state("a", last_status="ok")
    sch.save_task(sch.Task(name="b", agent="researcher", when="daily 08:00", prompt="x"),
                  original_name="a")
    assert not os.path.exists(os.path.join(sch.schedule_dir(), "a.md"))
    state = sch.load_state()
    assert state["b"]["last_status"] == "ok"
    assert "a" not in state


def test_delete_drops_file_and_state():
    make()
    sch.update_state("digest", last_status="ok")
    assert sch.delete_task("digest") is True
    assert sch.list_tasks() == [] and sch.load_state() == {}
    assert sch.delete_task("digest") is False


def test_set_enabled():
    make()
    assert sch.set_enabled("digest", False).enabled is False
    assert sch.get_task("digest").enabled is False


def test_broken_file_is_listed_and_never_due():
    os.makedirs(sch.schedule_dir(), exist_ok=True)
    with open(os.path.join(sch.schedule_dir(), "x.md"), "w") as f:
        f.write("---\nname: [unclosed\n---\nhi\n")
    [t] = sch.list_tasks()
    assert t.name == "x" and t.broken
    assert sch.due(dt(2026, 10, 7, 10)) == []


def test_corrupt_state_is_replaced():
    os.makedirs(sch.schedule_dir(), exist_ok=True)
    with open(sch.state_path(), "w") as f:
        f.write("{")
    assert sch.load_state() == {}
    sch.update_state("digest", last_status="ok")
    with open(sch.state_path()) as f:
        assert json.load(f) == {"digest": {"last_status": "ok"}}


def test_due_once_after_long_gap():
    make(created="2026-10-04T09:00:00")
    assert sch.due(dt(2026, 10, 7, 10, 0)) == [{"name": "digest", "slot": "2026-10-07T08:00:00"}]


def test_due_skips_disabled_tasks():
    make(enabled=False)
    assert sch.due(dt(2026, 10, 7, 10, 0)) == []


def test_missed_excludes_every_and_reset_every_moves_anchor():
    make(name="daily")
    make(name="often", when="every 30m")
    now = dt(2026, 10, 7, 10, 0)
    assert sch.missed(now) == [{"name": "daily", "when": "daily 08:00", "slot": "2026-10-07T08:00:00"}]
    sch.reset_every(now)
    assert sch.load_state()["often"]["anchor"] == "2026-10-07T10:00:00"
    assert sch.due(now) == [{"name": "daily", "slot": "2026-10-07T08:00:00"}]


def test_skip_records_slot_and_disables_once():
    make(name="d")
    make(name="o", when="once 2026-10-07 09:00")
    sch.skip("d", "2026-10-07T08:00:00")
    sch.skip("o", "2026-10-07T09:00:00")
    st = sch.load_state()
    assert st["d"] == {"anchor": "2026-10-07T08:00:00", "last_status": "skipped"}
    assert sch.get_task("o").enabled is False
    assert sch.due(dt(2026, 10, 7, 10, 0)) == []


def freeze(monkeypatch, *at):
    """Pin the engine's clock: claim() looks at "now" for the latest slot."""
    class Now(dt):
        @classmethod
        def now(cls, tz=None):
            return dt(*at)

    monkeypatch.setattr(sch, "datetime", Now)


def test_claim_is_once_per_slot(monkeypatch):
    make()
    freeze(monkeypatch, 2026, 10, 7, 9, 0)
    assert sch.claim("digest", "2026-10-07T08:00:00") is True
    assert sch.claim("digest", "2026-10-07T08:00:00") is False
    assert sch.claim("digest", None) is True
    assert sch.load_state()["digest"]["anchor"] == "2026-10-07T08:00:00"


def test_summary_of_collapses_and_truncates():
    assert sch.summary_of("  a\n\n b  ") == "a b"
    assert len(sch.summary_of("x" * 1000)) == 300


# ── Final review fixes ────────────────────────────────────────────────────────

def test_state_writes_are_safe_across_threads():
    import threading
    errors = []

    def writer(i):
        try:
            for n in range(60):
                sch.update_state(f"t{i}", n=n)
        except Exception as exc:          # noqa: BLE001 — any failure is the bug
            errors.append(exc)

    threads = [threading.Thread(target=writer, args=(i,)) for i in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == []
    assert {k: v["n"] for k, v in sch.load_state().items()} == {f"t{i}": 59 for i in range(4)}


def test_skip_never_moves_the_anchor_back(monkeypatch):
    make()
    freeze(monkeypatch, 2026, 10, 7, 9, 0)
    sch.claim("digest", "2026-10-07T08:00:00")
    sch.skip("digest", "2026-10-06T08:00:00")         # a late answer for an older slot
    assert sch.load_state()["digest"]["anchor"] == "2026-10-07T08:00:00"


def test_claim_takes_the_latest_passed_slot(monkeypatch):
    """A slot that waited in the queue while newer ones passed: running it
    covers them all, so the next check doesn't run the task again at once."""
    make(name="often", when="every 5m", created="2026-10-07T08:00:00")

    class Now(dt):
        @classmethod
        def now(cls, tz=None):
            return dt(2026, 10, 7, 8, 17)

    monkeypatch.setattr(sch, "datetime", Now)
    assert sch.claim("often", "2026-10-07T08:05:00") is True
    assert sch.load_state()["often"]["anchor"] == "2026-10-07T08:15:00"
    assert sch.due(dt(2026, 10, 7, 8, 17)) == []


def test_switching_a_task_back_on_starts_from_now(monkeypatch):
    make(created="2026-10-04T09:00:00")
    sch.set_enabled("digest", False)

    class Now(dt):
        @classmethod
        def now(cls, tz=None):
            return dt(2026, 10, 8, 15, 0)

    monkeypatch.setattr(sch, "datetime", Now)
    sch.set_enabled("digest", True)
    assert sch.due(dt(2026, 10, 8, 15, 0)) == []                 # not this morning's 08:00
    assert sch.due(dt(2026, 10, 9, 8, 0)) == [{"name": "digest", "slot": "2026-10-09T08:00:00"}]


def test_changing_the_time_starts_from_now(monkeypatch):
    make(created="2026-10-08T07:00:00")

    class Now(dt):
        @classmethod
        def now(cls, tz=None):
            return dt(2026, 10, 8, 10, 0)

    monkeypatch.setattr(sch, "datetime", Now)
    # The app sends the task back as it was, `created` included.
    sch.save_task(sch.Task(name="digest", agent="researcher", when="daily 09:00", prompt="x",
                           created="2026-10-08T07:00:00"), original_name="digest")
    assert sch.due(dt(2026, 10, 8, 10, 0)) == []                 # 09:00 today already passed


def test_an_aware_timestamp_in_a_file_does_not_break_the_schedule():
    os.makedirs(sch.schedule_dir(), exist_ok=True)
    with open(os.path.join(sch.schedule_dir(), "odd.md"), "w") as f:
        f.write("---\nname: odd\nagent: researcher\nwhen: daily 08:00\n"
                "created: 2026-10-06T09:00:00+00:00\n---\nhi\n")
    make(name="fine")
    names = {d["name"] for d in sch.due(dt(2026, 10, 7, 10, 0))}
    assert "fine" in names                                        # one odd file can't stop the rest


def test_original_name_cannot_leave_the_schedule_folder(tmp_path):
    victim = os.path.join(os.path.dirname(sch.schedule_dir()), "..", "victim.md")
    with open(victim, "w") as f:
        f.write("keep me")
    with pytest.raises(ValueError, match="bad task name"):
        sch.save_task(sch.Task(name="digest", agent="researcher", when="daily 08:00", prompt="x"),
                      original_name="../../victim")
    assert os.path.exists(victim)
    os.remove(victim)


def test_front_matter_name_must_match_the_file():
    os.makedirs(sch.schedule_dir(), exist_ok=True)
    with open(os.path.join(sch.schedule_dir(), "x.md"), "w") as f:
        f.write("---\nname: ../../x\nagent: researcher\nwhen: daily 08:00\n---\nhi\n")
    [t] = sch.list_tasks()
    assert t.name == "x" and t.broken
