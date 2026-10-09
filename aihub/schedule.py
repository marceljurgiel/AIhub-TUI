"""
AIHub — scheduled tasks.

A scheduled task runs an agent with a fixed prompt on a timetable, and only
while AIhub is open: the app keeps the clock and asks the engine what is due
(there is no background service). Each task is a Markdown file in
~/.aihub/schedule/<name>.md:

    ---
    name: mail-digest
    agent: assistant
    model: llama3.1:8b
    backend: ollama
    stream_model: llama3.1:8b
    when: daily 08:00
    enabled: true
    ---
    Summarize today's unread email in 5 bullets.

`when` is one of: every 30m · every 2h · daily 08:00 · weekdays 08:00 ·
weekly Mon 08:00 · once 2026-10-08 10:00 — local wall-clock time.
"""
from __future__ import annotations

import json
import logging
import os
import re
import tempfile
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

import yaml

from .config import CONFIG_DIR

log = logging.getLogger(__name__)

DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
MIN_EVERY_MINUTES = 5
FORMATS = ("every 30m · every 2h · daily 08:00 · weekdays 08:00 · "
           "weekly Mon 08:00 · once 2026-10-08 10:00")

_HM = r"(\d{1,2}):(\d{2})"
_EVERY = re.compile(r"^every\s+(\d+)\s*([mh])$")
_DAILY = re.compile(rf"^(daily|weekdays)\s+{_HM}$")
_WEEKLY = re.compile(rf"^weekly\s+([a-z]{{3}})[a-z]*\s+{_HM}$")
_ONCE = re.compile(rf"^once\s+(\d{{4}})-(\d{{1,2}})-(\d{{1,2}})\s+{_HM}$")


@dataclass(frozen=True)
class When:
    kind: str                      # every | daily | weekdays | weekly | once
    minutes: int = 0               # every
    hour: int = 0
    minute: int = 0
    weekday: int = 0               # weekly: 0 = Monday
    at: Optional[datetime] = None  # once
    text: str = ""                 # canonical form, as saved in the task file


def _bad(text: str) -> ValueError:
    return ValueError(f"unknown schedule {text.strip()!r} — use one of: {FORMATS}")


def _hm(text: str, h: str, m: str) -> tuple:
    hour, minute = int(h), int(m)
    if hour > 23 or minute > 59:
        raise _bad(text)
    return hour, minute


def parse_when(text: str) -> When:
    """Parse a schedule like "daily 08:00"; ValueError lists the accepted forms."""
    s = " ".join(str(text or "").lower().split())
    if m := _EVERY.match(s):
        n, unit = int(m.group(1)), m.group(2)
        minutes = n * (60 if unit == "h" else 1)
        if minutes < MIN_EVERY_MINUTES:
            raise _bad(text)
        return When("every", minutes=minutes, text=f"every {n}{unit}")
    if m := _DAILY.match(s):
        hour, minute = _hm(text, m.group(2), m.group(3))
        return When(m.group(1), hour=hour, minute=minute, text=f"{m.group(1)} {hour:02d}:{minute:02d}")
    if m := _WEEKLY.match(s):
        day = m.group(1).capitalize()
        if day not in DAYS:
            raise _bad(text)
        hour, minute = _hm(text, m.group(2), m.group(3))
        return When("weekly", hour=hour, minute=minute, weekday=DAYS.index(day),
                    text=f"weekly {day} {hour:02d}:{minute:02d}")
    if m := _ONCE.match(s):
        hour, minute = _hm(text, m.group(4), m.group(5))
        try:
            at = datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)), hour, minute)
        except ValueError:
            raise _bad(text) from None
        return When("once", at=at, hour=hour, minute=minute, text=f"once {at:%Y-%m-%d %H:%M}")
    raise _bad(text)


def next_run(when: When, after: datetime) -> Optional[datetime]:
    """The first slot strictly after `after` (None: a `once` that has passed)."""
    if when.kind == "every":
        return after + timedelta(minutes=when.minutes)
    if when.kind == "once":
        return when.at if when.at and when.at > after else None
    day = after.replace(hour=when.hour, minute=when.minute, second=0, microsecond=0)
    if day <= after:
        day += timedelta(days=1)
    # Calendar arithmetic on naive datetimes keeps the wall-clock time across
    # DST changes: 08:00 stays 08:00.
    while not _runs_on(when, day):
        day += timedelta(days=1)
    return day


def _runs_on(when: When, day: datetime) -> bool:
    if when.kind == "weekdays":
        return day.weekday() < 5
    if when.kind == "weekly":
        return day.weekday() == when.weekday
    return True


def latest_slot(when: When, anchor: datetime, now: datetime) -> Optional[datetime]:
    """The last slot in (anchor, now], or None — one slot however many passed
    (a laptop that slept through three mornings runs the task once)."""
    if when.kind == "every":
        steps = int((now - anchor) / timedelta(minutes=when.minutes))
        return anchor + steps * timedelta(minutes=when.minutes) if steps >= 1 else None
    if when.kind == "once":
        return when.at if when.at and anchor < when.at <= now else None
    # A calendar slot repeats at least weekly, so only the last 8 days matter.
    start = max(anchor, now - timedelta(days=8))
    found = None
    slot = next_run(when, start)
    while slot is not None and slot <= now:
        found = slot
        slot = next_run(when, slot)
    return found


# ── Task files ───────────────────────────────────────────────────────────────

_NAME = re.compile(r"^[a-z0-9][a-z0-9_-]{0,31}$")
SUMMARY_CHARS = 300


def _default_agent() -> str:
    from .agents import DEFAULT_AGENT
    return DEFAULT_AGENT


@dataclass
class Task:
    name: str
    agent: str = field(default_factory=_default_agent)
    model: str = ""
    backend: str = "ollama"
    stream_model: str = ""
    when: str = ""
    prompt: str = ""
    enabled: bool = True
    created: str = ""              # ISO; the baseline before the first run
    broken: str = ""               # why the file couldn't be read ("" = fine)
    path: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def schedule_dir() -> str:
    return os.path.join(CONFIG_DIR, "schedule")


def state_path() -> str:
    return os.path.join(schedule_dir(), "state.json")


def _task_path(name: str) -> str:
    return os.path.join(schedule_dir(), f"{name}.md")


def _write_atomic(path: str, text: str) -> None:
    d = os.path.dirname(path)
    os.makedirs(d, exist_ok=True)
    # A tmp file of its own: two writers must never share (and move) one.
    fd, tmp = tempfile.mkstemp(dir=d, prefix=".tmp-", suffix=".part")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise


def _state_lock():
    """Serialise read-modify-write of the run state: between the bridge's
    request threads, and between two AIhub windows (an OS file lock)."""
    from .filelock import file_lock
    return file_lock(os.path.join(schedule_dir(), ".lock"))


def _parse_task(text: str, path: str) -> Task:
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n?(.*)$", text, re.DOTALL)
    if not m:
        raise ValueError("missing the --- front matter --- block")
    meta = yaml.safe_load(m.group(1)) or {}
    if not isinstance(meta, dict):
        raise ValueError("front matter must be key: value pairs")
    stem = os.path.splitext(os.path.basename(path))[0]
    if not _NAME.match(stem):
        raise ValueError(f"bad file name {stem!r}: use a-z, 0-9, - or _ (max 32)")
    if meta.get("name") is not None and str(meta["name"]) != stem:
        raise ValueError(f"name {meta['name']!r} doesn't match the file name {stem!r}")
    return Task(
        name=stem,
        agent=str(meta.get("agent") or _default_agent()),
        model=str(meta.get("model") or ""),
        backend=str(meta.get("backend") or "ollama"),
        stream_model=str(meta.get("stream_model") or ""),
        when=str(meta.get("when") or ""),
        prompt=m.group(2).strip(),
        enabled=bool(meta.get("enabled", True)),
        created=str(meta.get("created") or ""),
        path=path,
    )


def _render_task(t: Task) -> str:
    meta = {"name": t.name, "agent": t.agent, "model": t.model, "backend": t.backend,
            "stream_model": t.stream_model, "when": t.when, "enabled": t.enabled,
            "created": t.created}
    head = yaml.safe_dump(meta, sort_keys=False, allow_unicode=True).strip()
    return f"---\n{head}\n---\n{t.prompt.strip()}\n"


def list_tasks() -> List[Task]:
    """All tasks by name. A file that can't be read is listed as broken (with
    the reason) rather than vanishing, so the user can fix or delete it."""
    d = schedule_dir()
    out: List[Task] = []
    if not os.path.isdir(d):
        return out
    for fn in sorted(os.listdir(d)):
        if not fn.endswith(".md"):
            continue
        path = os.path.join(d, fn)
        try:
            with open(path, encoding="utf-8") as f:
                t = _parse_task(f.read(), path)
            parse_when(t.when)
        except Exception as exc:
            log.warning("task file %s is broken: %s", path, exc)
            t = Task(name=fn[:-3], broken=str(exc) or type(exc).__name__, enabled=False, path=path)
        out.append(t)
    return out


def get_task(name: str) -> Task:
    for t in list_tasks():
        if t.name == name:
            return t
    raise KeyError(f"no task named {name!r}")


def save_task(task: Task, original_name: Optional[str] = None) -> Task:
    """Validate and write a task. `original_name` marks an edit (and a rename
    when it differs): the run state follows the task to its new name."""
    from .agents import get_agent
    task.name = task.name.strip().lower()
    for n in (task.name, original_name):
        if n is not None and not _NAME.match(n):
            raise ValueError(f"bad task name {n!r}: use a-z, 0-9, - or _ (max 32)")
    task.when = parse_when(task.when).text
    task.prompt = task.prompt.strip()
    if not task.prompt:
        raise ValueError("the task needs a prompt")
    try:
        get_agent(task.agent)
    except KeyError:
        raise ValueError(f"no agent named {task.agent!r} — pick one from Agents") from None
    if task.name != original_name and os.path.exists(_task_path(task.name)):
        raise ValueError(f"a task named {task.name!r} already exists")
    if not task.created:
        task.created = _iso(datetime.now())
    before = None
    if original_name:
        try:
            before = get_task(original_name)
        except KeyError:
            pass
    task.broken = ""
    task.path = _task_path(task.name)
    _write_atomic(task.path, _render_task(task))
    with _state_lock():
        state = load_state()
        if original_name and original_name != task.name:
            old = _task_path(original_name)
            if os.path.exists(old):
                os.remove(old)
            if original_name in state:
                state[task.name] = state.pop(original_name)
        # A new time, or switched back on: count from now, so a slot that
        # passed before the edit doesn't run straight away.
        if before and not before.broken and (before.when != task.when or (task.enabled and not before.enabled)):
            state.setdefault(task.name, {})["anchor"] = _iso(datetime.now())
        _save_state(state)
    return task


def delete_task(name: str) -> bool:
    # Any plain file name in the folder: a broken file may have an odd one.
    if not name or os.path.basename(name) != name or name.startswith("."):
        return False
    path = _task_path(name)
    if not os.path.exists(path):
        return False
    os.remove(path)
    with _state_lock():
        state = load_state()
        if state.pop(name, None) is not None:
            _save_state(state)
    return True


def set_enabled(name: str, enabled: bool) -> Task:
    t = get_task(name)
    if t.broken:
        raise ValueError(f"task {name!r} is broken: {t.broken}")
    was = t.enabled
    t.enabled = bool(enabled)
    _write_atomic(t.path, _render_task(t))
    if t.enabled and not was:
        # Back on: the next future slot, not one that passed while it was off.
        update_state(name, anchor=_iso(datetime.now()))
    return t


# ── Run state ────────────────────────────────────────────────────────────────
# Kept apart from the task files so editing a prompt keeps the run history.
# Per task: anchor (the latest handled slot, or the startup reset point),
# last_run, last_status (ok|error|cancelled|skipped), last_summary,
# last_session ({model, filename}), last_error.

def load_state() -> Dict[str, Dict[str, Any]]:
    try:
        with open(state_path(), encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as exc:
        log.warning("schedule state %s unreadable, starting fresh: %s", state_path(), exc)
        return {}


def _save_state(state: Dict[str, Dict[str, Any]]) -> None:
    _write_atomic(state_path(), json.dumps(state, indent=1, ensure_ascii=False))


def update_state(name: str, **fields: Any) -> None:
    with _state_lock():
        state = load_state()
        state.setdefault(name, {}).update(fields)
        _save_state(state)


def record_run(name: str, **fields: Any) -> None:
    """Like update_state, but only for a task that still exists (one deleted
    while it ran leaves no state behind)."""
    with _state_lock():
        if not os.path.exists(_task_path(name)):
            return
        state = load_state()
        state.setdefault(name, {}).update(fields)
        _save_state(state)


def _iso(d: datetime) -> str:
    return d.replace(microsecond=0).isoformat()


def anchor_of(task: Task, state: Dict[str, Dict[str, Any]]) -> datetime:
    """Slots after this point are pending: the last handled slot, else the
    task's creation, else now (a hand-written file, recorded on first sight)."""
    raw = (state.get(task.name) or {}).get("anchor") or task.created
    try:
        d = datetime.fromisoformat(str(raw))
        # Schedules are naive local time; a hand-written "+02:00" is converted.
        return d.astimezone().replace(tzinfo=None) if d.tzinfo else d
    except (TypeError, ValueError):
        now = datetime.now()
        update_state(task.name, anchor=_iso(now))
        return now


def _pending(now: datetime, include_every: bool) -> List[Dict[str, Any]]:
    state = load_state()
    out = []
    for t in list_tasks():
        if t.broken or not t.enabled:
            continue
        try:
            w = parse_when(t.when)
            if w.kind == "every" and not include_every:
                continue
            slot = latest_slot(w, anchor_of(t, state), now)
        except Exception:
            # One odd task must not stop every other one.
            log.warning("schedule of task %s can't be computed", t.name, exc_info=True)
            continue
        if slot is not None:
            out.append({"name": t.name, "when": t.when, "slot": _iso(slot)})
    return out


def due(now: datetime) -> List[Dict[str, Any]]:
    """Tasks with a slot since they last ran: [{name, slot}]."""
    return [{"name": p["name"], "slot": p["slot"]} for p in _pending(now, True)]


def missed(now: datetime) -> List[Dict[str, Any]]:
    """At startup: calendar tasks whose slot passed while AIhub was closed
    ([{name, when, slot}]); the app asks before running them. `every` tasks
    just start over (see reset_every)."""
    return _pending(now, False)


def reset_every(now: datetime) -> None:
    every = [t.name for t in list_tasks() if not t.broken and t.when.startswith("every")]
    if not every:
        return
    with _state_lock():
        state = load_state()
        for n in every:
            state.setdefault(n, {})["anchor"] = _iso(now)
        _save_state(state)


def skip(name: str, slot: str) -> None:
    with _state_lock():
        state = load_state()
        st = state.setdefault(name, {})
        st["anchor"] = max(slot, st.get("anchor") or "")     # never backwards
        st["last_status"] = "skipped"
        _save_state(state)
    t = get_task(name)
    if t.when.startswith("once"):
        set_enabled(name, False)


def claim(name: str, slot: Optional[str]) -> bool:
    """Mark a scheduled slot as taken before running it; False when it already
    was (another AIhub window got there first). The anchor moves to the latest
    slot that has passed, so a slot that waited in the queue covers the newer
    ones too. A manual run (no slot) never moves the anchor."""
    if slot is None:
        return True
    with _state_lock():
        state = load_state()
        st = state.setdefault(name, {})
        current = st.get("anchor") or ""
        if current >= slot:
            return False
        newest = slot
        try:
            t = get_task(name)
            latest = latest_slot(parse_when(t.when), datetime.fromisoformat(slot), datetime.now())
            if latest is not None:
                newest = max(newest, _iso(latest))
        except (KeyError, ValueError):
            pass
        st["anchor"] = newest
        _save_state(state)
    return True


def summary_of(text: str) -> str:
    return " ".join(str(text or "").split())[:SUMMARY_CHARS]
