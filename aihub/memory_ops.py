"""
AIHub — structured operations on the memory file.

The memory file stays human-editable Markdown (the ^E dialog edits it):

    <!-- AIHub Memory File — created: … -->     ← preamble, kept as is
    ## Topic
    One fact about the user.

Every writer — the automatic learner, the model's `remember` tool, the
`/memory save` command — goes through `apply_ops`, which is deterministic
code, so safety doesn't depend on how good the model is:

  * secret-looking facts are refused when `strict` (passwords, API keys…),
  * a topic matches an existing one case-insensitively; a new fact for it is
    ADDED as another line — it replaces the topic only when it says something
    changed ("no longer", "switched to", "już nie", "teraz"…) — at most one
    such replacement per batch — or when the user writes it (/memory save),
  * a fact that's already known — under any topic — is not added again, and
    one fact lands under one topic only (small models file the same fact
    under several topics),
  * at most MAX_LINES facts per topic,
  * at most MAX_OPS changes per call, facts and topics are length-capped.

Each applied change is appended to changes.jsonl next to the memory file,
which is what `undo` reads.
"""
from __future__ import annotations

import json
import logging
import os
import difflib
import re
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional, Tuple

log = logging.getLogger(__name__)

MAX_OPS = 5
MAX_FACT = 300
MAX_TOPIC = 60
MAX_LINES = 8

# A fact that says something changed replaces the topic instead of adding.
_CHANGED = re.compile(
    r"(?i)\b(no longer|not any ?more|anymore|instead|switched|moved|changed|now|stopped|quit"
    r"|już nie|juz nie|nie \w+ już|zamiast|przesiad\w*|przeni\w*|przeprowadzi\w*|zmieni\w*"
    r"|teraz|obecnie|od teraz|przesta\w*|sprzeda\w*)\b"
)

# Conservative on purpose: a fact that merely mentions a password manager is
# dropped too — memory is sent with every prompt, possibly to a cloud API.
_SECRET = re.compile(
    r"(?i)\b(pass(word|wd|phrase)?|hasł\w*|pin|token\w*|api[ _-]?keys?|klucz\w*|secret\w*|sekret\w*|credential\w*)\b"
    r"|\bsk-[A-Za-z0-9_-]{8,}|\bgh[pousr]_[A-Za-z0-9]{20,}|\bAKIA[0-9A-Z]{16}\b"
    r"|\b[A-Fa-f0-9]{32,}\b|-----BEGIN [A-Z ]*PRIVATE KEY-----"
)

_HEADER = re.compile(r"^## (.+?)\s*$", re.MULTILINE)


@dataclass
class Entry:
    topic: str
    fact: str


@dataclass
class Change:
    """One applied edit. `before`/`after` are the fact text (None = absent)."""
    op: str
    topic: str
    before: Optional[str]
    after: Optional[str]
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:10])
    batch: str = ""
    ts: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))
    source: Dict[str, Any] = field(default_factory=dict)


# ── Parse / render ────────────────────────────────────────────────────────────

def parse_memory(md: str) -> Tuple[str, List[Entry]]:
    """Split the file into (preamble, entries). Text before the first
    "## " heading (the header comment, free notes) is the preamble."""
    matches = list(_HEADER.finditer(md))
    if not matches:
        return md.strip(), []
    preamble = md[: matches[0].start()].strip()
    entries = []
    for i, m in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(md)
        entries.append(Entry(m.group(1).strip(), md[m.end():end].strip()))
    return preamble, entries


def render_memory(preamble: str, entries: Iterable[Entry]) -> str:
    parts = [preamble.strip()] if preamble.strip() else []
    parts += [f"## {e.topic}\n{e.fact}".rstrip() for e in entries]
    return "\n\n".join(parts).strip() + "\n"


# ── Pure planning (no I/O) ────────────────────────────────────────────────────

def _clean(text: Any, limit: int) -> str:
    return " ".join(str(text or "").split())[:limit].strip()


def _norm(text: str) -> str:
    return re.sub(r"[\W_]+", " ", text.lower()).strip()


_FILLER = {
    "user", "users", "uses", "using", "used", "likes", "prefers", "works", "lives", "have", "has",
    "with", "from", "that", "this", "their", "about", "longer", "anymore", "currently", "now",
    "użytkownik", "używa", "używał", "lubi", "woli", "preferuje", "pracuje", "mieszka", "jest",
    "oraz", "teraz", "obecnie", "który", "która", "które", "jego", "swój", "swoje", "swoją", "także",
}


def _words(text: str) -> set:
    """Content words (lower-case, filler removed) plus numbers / IP-like tokens."""
    out = set()
    for w in re.findall(r"[\w.:/-]+", (text or "").lower()):
        w = w.strip(".:/-")
        if any(ch.isdigit() for ch in w) or (len(w) >= 4 and w not in _FILLER):
            out.add(w)
    return out


def _same_word(a: str, b: str) -> bool:
    """Loose match for inflected forms: Neovim/Neovima, Burek/Burka,
    Lizbona/Lizbony. Numbers must match exactly."""
    if a == b:
        return True
    if any(ch.isdigit() for ch in a + b):
        return False
    n = len(os.path.commonprefix([a, b]))
    return n >= 4 or (n >= 3 and len(a) >= 5 and len(b) >= 5)


def _supported(evidence: set, said: set) -> bool:
    return any(_same_word(e, s) for e in evidence for s in said)


# A fact needs at least this share of its content words in what the user
# said. One shared word let invented sentences through (a garbled sentence
# passed on one place name); a third still lets an English fact stand on
# the names, places and cognates of a Polish message ("Works as a graphic
# designer." ← "pracuję jako grafik").
FACT_SUPPORT = 1 / 3


def _share(text: str, said: set, share: float) -> bool:
    words = _words(text)
    hits = sum(1 for w in words if any(_same_word(w, s) for s in said))
    return hits > 0 and hits >= share * len(words)


def fact_supported(fact: str, said: set) -> bool:
    return _share(fact, said, FACT_SUPPORT)


def _flat(text: str) -> str:
    return " ".join(re.findall(r"\w+", (text or "").lower()))


def quote_in(quote: str, texts: List[str]) -> bool:
    """The memory model's quote of the user's own words: a stretch of one
    message, word for word (case and punctuation aside), with at least one
    content word. This grounds an English fact taken from a message in any
    language ("Lives in Lisbon." ← "mieszkam w lizbonie")."""
    q = _flat(quote)
    return bool(q) and bool(_words(quote)) and any(f" {q} " in f" {_flat(t)} " for t in texts)


_TOKEN = re.compile(r"[\w.:/-]+")


def _close(a: str, b: str) -> bool:
    """Same word, an inflection of it, or the same name spelled another way
    (Lisbon / Lizbonie, NeoVim / neovima)."""
    if any(ch.isdigit() for ch in a + b):
        return a == b
    if _same_word(a, b):
        return True
    # Against b's start at a few lengths, so an ending (-ie, -a, -ów) can't
    # sink the match.
    return len(a) >= 3 and max(difflib.SequenceMatcher(None, a, b[:n]).ratio()
                               for n in range(max(1, len(a) - 1), len(a) + 3)) >= 0.75


def names_supported(fact: str, texts: List[str]) -> bool:
    """Every name and number in a fact must be the user's: a model that
    quotes real words can still invent "a dog named Rex" or "Porto Bank".
    A name is a capitalised word after the first; a number has a digit."""
    said = [t.strip(".:/-").lower() for t in _TOKEN.findall(" ".join(texts))]
    for i, tok in enumerate(_TOKEN.findall(fact or "")):
        tok = tok.strip(".:/-")
        if not tok:
            continue
        if any(ch.isdigit() for ch in tok) or (i > 0 and tok[:1].isupper()):
            if not any(_close(tok.lower(), s) for s in said if s):
                return False
    return True


def same_fact(new: str, old: str) -> bool:
    """Is `new` already said by `old`? Exact after normalising, or every
    content word of `new` is (an inflection of) a word of `old` —
    "Uses Neovima" is known when memory says "Neovim"."""
    if _norm(new) == _norm(old):
        return True
    words = _words(new)
    have = _words(old)
    return bool(words) and all(any(_same_word(w, h) for h in have) for w in words)


def looks_secret(text: str) -> bool:
    return bool(_SECRET.search(text))


def _find(entries: List[Entry], topic: str) -> Optional[int]:
    want = _norm(topic)
    for i, e in enumerate(entries):
        if _norm(e.topic) == want:
            return i
    return None


def plan_ops(md: str, ops: Iterable[Dict[str, Any]], *, strict: bool = True,
             source: Optional[Dict[str, Any]] = None) -> Tuple[str, List[Change]]:
    """Apply `ops` to the memory text without touching disk. Returns the new
    text and the changes that actually happened (skipped ops leave none)."""
    preamble, entries = parse_memory(md)
    changes: List[Change] = []
    batch = uuid.uuid4().hex[:8]
    replaced_one = False
    for raw in list(ops)[:MAX_OPS]:
        if not isinstance(raw, dict):
            continue
        op = str(raw.get("op", "")).lower()
        topic = _clean(raw.get("topic"), MAX_TOPIC)
        # Learned facts are normalised and capped; what the user typed
        # themself (/memory save) is kept as written.
        fact = _clean(raw.get("fact"), MAX_FACT) if strict else str(raw.get("fact") or "").strip()
        if op not in ("add", "update", "forget") or not topic:
            continue
        if strict and looks_secret(f"{topic} {fact}"):
            log.info("memory: refused a secret-looking %s on %r", op, topic)
            continue
        idx = _find(entries, topic)
        if op == "forget":
            if idx is None:
                continue
            gone = entries.pop(idx)
            changes.append(Change("forget", gone.topic, gone.fact, None, batch=batch, source=source or {}))
            continue
        if not fact:
            continue
        if any(same_fact(fact, line) for e in entries for line in e.fact.splitlines() if line.strip()):
            continue                                          # known (any topic, any line)
        if idx is not None:
            current = entries[idx]
            # Learned facts replace at most one topic per batch — a confused
            # model can't wipe several topics with one "change".
            replace = not strict or (bool(raw.get("replace") or _CHANGED.search(fact))
                                     and not any(c.op == "update" and c.after == fact for c in changes)
                                     and not replaced_one)
            replaced_one = replaced_one or (strict and replace)
            lines = [ln for ln in current.fact.splitlines() if ln.strip()]
            if not replace and len(lines) >= MAX_LINES:
                log.info("memory: topic %r is full — %r not added", current.topic, fact)
                continue
            new = fact if replace else "\n".join(lines + [fact])
            changes.append(Change("update", current.topic, current.fact, new, batch=batch, source=source or {}))
            current.fact = new
        else:
            entries.append(Entry(topic, fact))
            changes.append(Change("add", topic, None, fact, batch=batch, source=source or {}))
    if not changes:
        return md, []
    if "<!-- AIHub Memory File" not in preamble:
        stamp = f"<!-- AIHub Memory File — created: {datetime.now():%Y-%m-%d} -->"
        preamble = f"{stamp}\n\n{preamble}".strip()
    return render_memory(preamble, entries), changes


# ── Disk ──────────────────────────────────────────────────────────────────────

def _log_path() -> str:
    from .memory import get_memory_path
    return os.path.join(os.path.dirname(get_memory_path()), "changes.jsonl")


def _append_log(records: Iterable[Dict[str, Any]]) -> None:
    path = _log_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def apply_ops(ops: Iterable[Dict[str, Any]], *, strict: bool = True,
              source: Optional[Dict[str, Any]] = None) -> List[Change]:
    """Apply ops to the memory file and record them. Reads the file strictly:
    an unreadable file raises rather than being rewritten from scratch."""
    from .memory import _read_memory, save_memory

    new_md, changes = plan_ops(_read_memory(), ops, strict=strict, source=source)
    if changes:
        save_memory(new_md)
        _append_log(asdict(c) for c in changes)
    return changes


def read_log() -> List[Dict[str, Any]]:
    try:
        with open(_log_path(), encoding="utf-8") as f:
            return [json.loads(line) for line in f if line.strip()]
    except FileNotFoundError:
        return []


def undo(change_ids: Iterable[str]) -> List[Change]:
    """Revert the given changes (newest first). A change is only reverted if
    the topic still holds the value it set — a later manual edit wins."""
    from .memory import _read_memory, save_memory

    wanted = set(change_ids)
    done_ids = {r["undoes"] for r in read_log() if r.get("op") == "undo"}
    targets = [r for r in read_log() if r.get("id") in wanted and r["id"] not in done_ids]
    preamble, entries = parse_memory(_read_memory())
    reverted: List[Change] = []
    for r in reversed(targets):
        idx = _find(entries, r["topic"])
        current = entries[idx].fact if idx is not None else None
        if (current or None) != r.get("after"):
            continue                                          # edited since
        if r.get("before") is None:
            if idx is not None:
                entries.pop(idx)                              # undo an add
        elif idx is None:
            entries.append(Entry(r["topic"], r["before"]))    # undo a forget
        else:
            entries[idx].fact = r["before"]                   # undo an update
        reverted.append(Change("undo", r["topic"], r.get("after"), r.get("before")))
        _append_log([{"op": "undo", "undoes": r["id"], "ts": datetime.now().isoformat(timespec="seconds")}])
    if reverted:
        save_memory(render_memory(preamble, entries))
    return reverted


def last_batch_ids() -> List[str]:
    """Ids of the most recent batch of changes that hasn't been undone."""
    records = read_log()
    undone = {r["undoes"] for r in records if r.get("op") == "undo"}
    live = [r for r in records if r.get("op") in ("add", "update", "forget") and r["id"] not in undone]
    if not live:
        return []
    batch = live[-1].get("batch")
    return [r["id"] for r in live if r.get("batch") == batch]
