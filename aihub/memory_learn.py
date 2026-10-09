"""
AIHub — automatic memory: learn durable facts about the user from chats.

Built so a small model (1–4B) is enough:

1. `self_disclosing()` — a plain-code filter. Only messages where the user
   talks about themself ("I use…", "mam…", "pracuję…", "już nie…") go on;
   most messages (questions, tasks) never reach a model at all.
2. The model gets a narrow job: list the durable facts in those messages as
   {topic, fact, still_true}, reusing an existing topic name when the fact is
   about the same thing. It does NOT decide add vs update vs duplicate.
3. `memory_ops.apply_ops` (code) turns facts into add / update / forget,
   skips what's already known, refuses secrets, and logs every change.

Only the USER's messages are read: never tool results, file contents or web
pages (so quoted text can't inject facts), nor the assistant's replies.
"""
from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional, Tuple

log = logging.getLogger(__name__)

MAX_MESSAGE_CHARS = 1500
MAX_TOTAL_CHARS = 6000

# ── 1. Filter: does the user say something about themself? ───────────────────

_SELF = re.compile(
    r"(?ix)"
    # English first person + durable verbs
    r"\b(i\ ?'?m|i\ am|i\ use|i\ work|i\ live|i\ have|i\ prefer|i\ like|i\ love|i\ hate|i\ switched"
    r"|i\ moved|i\ no\ longer|i\ don'?t\ use|i\ run|i\ own|i\ speak|i'?ve\ (got|switched|moved)"
    r"|my\ |mine\b|call\ me\b|remember\b|don'?t\ forget)"
    # Polish first person (verbs in 1st person singular, possessives)
    r"|\b(jestem|mam|nie\ mam|używam|nie\ używam|pracuję|mieszkam|lubię|nie\ lubię|wolę|kocham"
    r"|nienawidzę|preferuję|przesiadłem|przesiadłam|przeniosłem|przeniosłam|przeprowadzam|przeprowadziłem"
    r"|sprzedałem|sprzedałam|kupiłem|kupiłam|uczę\ się|zaczynam|zacząłem|zaczęłam|mówię|programuję"
    r"|piszę\ w|zwykle|od\ teraz|już\ nie|mój|moja|moje|moi|mojego|mojej|moim|zapamiętaj|pamiętaj|nie\ zapomnij"
    r"|nazywam\ się|mam\ na\ imię)\b"
)


_QUOTED = re.compile(
    r"```.*?```"                                   # fenced code / pasted files
    r"|([\"'„“”‘’«»]).{20,}?[\"'„“”‘’«»]",           # long quoted passages
    re.DOTALL,
)


_SKILL_MSG = re.compile(r'^Use the "[^"]+" skill for this\..*?\n\nTask: (.*)$', re.DOTALL)
_SKILL_BLOCK = re.compile(r"<skill name=\"[^\"]*\">.*?</skill>", re.DOTALL)


def strip_quoted(text: str) -> str:
    """Remove pasted code, long quoted passages and skill instructions: words
    the user quotes (a file, a web page, a /skill's instructions) are not
    facts about the user — and the classic way to inject "remember that my
    name is Bob", or to make a model "forget" things the text mentions."""
    t = text or ""
    m = _SKILL_MSG.match(t)
    if m:                                   # a /skill message: only the user's task counts
        t = m.group(1)
    t = _SKILL_BLOCK.sub(" [skill] ", t)
    return _QUOTED.sub(" [quoted] ", t)


# Sentences about someone else ("my colleague Tomek uses Windows") aren't
# facts about the user. (Loses "I have a brother" — acceptable.)
_OTHERS = re.compile(
    r"(?i)\b(kolega|koleżanka|znajom\w*|przyjaciel\w*|brat\w*|siostr\w*|żona|żony|mąż|męża|mama|mamy|tata|taty"
    r"|ojciec|matka|syn\w*|córk\w*|szef\w*|friend|colleague|coworker|co-worker|wife|husband|brother|sister"
    r"|mom|mum|dad|mother|father|son|daughter|boss|partner)\b"
)


def drop_others(text: str) -> str:
    sentences = re.split(r"(?<=[.!?\n])\s+", text or "")
    return " ".join(x for x in sentences if not _OTHERS.search(x))


# Broader net: any Polish 1st-person-singular-looking verb (gram, piszę,
# jestem…), "mi / mnie / always / never", or an English "I". A word list
# alone always misses something ("Gram na gitarze"); a false positive only
# costs one model call.
_SELF_LOOSE = re.compile(
    r"(?i)\b[a-ząćęłńóśźż]{2,}(ę|am|em)\b|\b(mi|mnie|ze mną|zawsze|nigdy|always|never|me)\b"
)
_ENGLISH_I = re.compile(r"\bI\b")


def self_disclosing(text: str) -> bool:
    """Cheap pre-filter: might this message state a fact about the user?"""
    t = text or ""
    return bool(_SELF.search(t) or _SELF_LOOSE.search(t) or _ENGLISH_I.search(t))


# ── 2. Narrow extraction ──────────────────────────────────────────────────────

FACTS_SCHEMA = {
    "type": "object",
    "properties": {
        "facts": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "topic": {"type": "string"},
                    "fact": {"type": "string"},
                    "quote": {"type": "string"},
                    "still_true": {"type": "boolean"},
                },
                "required": ["topic", "fact", "quote", "still_true"],
            },
        },
    },
    "required": ["facts"],
}

SYSTEM_PROMPT = """List durable facts the user states about THEMSELF in the messages.
Durable = worth knowing in future chats: name, job, location, spoken language,
tools / editor / programming languages, hardware, servers, projects, pets,
diet, schedule, answer-style preferences, lasting plans.
Skip: questions, one-off tasks, hypotheticals ("if I had…"), other people,
text quoted from files or websites, and passwords / keys / PINs.
For each fact: a short English topic; the fact as one short English sentence
in the third person, without "I" (e.g. "Lives in Porto."), whatever language
the user writes in; keep names, places and numbers as the user wrote them;
quote = the user's own words the fact comes from, copied exactly from the
message; still_true=false only if the user says it is no longer true.
One fact per entry: a message with two facts gives two entries, each under
its own topic.
If the fact is about the same thing as a known topic, use that exact topic name.
If there is nothing durable, return {"facts": []}.

Example: "Mam Toyotę i mieszkam w Porto, a PIN do karty to 1234." (known topics: Car)
-> {"facts": [{"topic": "Car", "fact": "Drives a Toyota.", "quote": "Mam Toyotę", "still_true": true}, {"topic": "Location", "fact": "Lives in Porto.", "quote": "mieszkam w Porto", "still_true": true}]}
Example: "I don't drink coffee any more." (known topics: Drinks)
-> {"facts": [{"topic": "Drinks", "fact": "No longer drinks coffee.", "quote": "I don't drink coffee any more", "still_true": false}]}"""


def build_messages(memory_md: str, user_texts: List[str]) -> List[Dict[str, str]]:
    from .memory_ops import parse_memory

    budget = MAX_TOTAL_CHARS
    lines = []
    for text in user_texts:
        t = " ".join(str(text).split())[:MAX_MESSAGE_CHARS][:budget]
        if not t:
            continue
        budget -= len(t)
        lines.append(f"- {t}")
    topics = ", ".join(e.topic for e in parse_memory(memory_md)[1]) or "(none)"
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": f"Known topics: {topics}\n\nMessages:\n" + "\n".join(lines)},
    ]


_RETRACT = re.compile(
    r"(?i)\b(no longer|not any ?more|anymore|don'?t (have|use)|sold|got rid|stopped"
    r"|już nie|nie \w+ już|nie używam|sprzeda\w*|pozby\w*|przestał\w*|zrezygnowa\w*)\b"
)


def reconcile(ops: List[Dict[str, Any]], memory_md: str) -> List[Dict[str, Any]]:
    """Small models often file "I don't have my Raspberry Pi any more" as a
    new fact under a random topic. If a fact says something is gone and
    matches a remembered fact, forget THAT topic instead."""
    from .memory_ops import _same_word, _words, parse_memory

    entries = parse_memory(memory_md)[1]
    out = []
    for op in ops:
        if op["op"] != "forget" and _RETRACT.search(op.get("fact", "")):
            said = _words(op["fact"])
            hit = next((e for e in entries
                        if any(_same_word(w, h) for w in said for h in _words(e.fact))), None)
            if hit:
                old = _words(hit.fact)
                new = {w for w in said if not any(_same_word(w, h) for h in old)}
                # Pure retraction → forget; "no longer X, now Y" → replace X.
                quote = {"quote": op["quote"]} if op.get("quote") else {}
                op = ({"op": "update", "topic": hit.topic, "fact": op["fact"], **quote} if new
                      else {"op": "forget", "topic": hit.topic, "fact": op["fact"]})
        out.append(op)
    return out


MAX_FORGETS = 2


def facts_to_ops(facts: Any) -> List[Dict[str, Any]]:
    """Model output → memory ops. Code, not the model, picks the operation:
    apply_ops adds a new topic, updates a known one, skips an unchanged one.
    A model that marks more than MAX_FORGETS topics "no longer true" at once
    is lost (seen: llama3.2:3b on a pasted skill marked all 11 topics false
    with "[no fact provided]") — none of its forgets count."""
    ops = []
    retract = [f for f in (facts if isinstance(facts, list) else [])
               if isinstance(f, dict) and f.get("still_true") is False]
    drop_forgets = len(retract) > MAX_FORGETS
    if drop_forgets:
        log.info("memory: model wanted to forget %d topics at once — ignored", len(retract))
    for f in facts if isinstance(facts, list) else []:
        if not isinstance(f, dict):
            continue
        if "?" in str(f.get("fact", "")):
            continue          # a question isn't a fact ("Name: Jak mam na imię?")
        if f.get("still_true") is False and drop_forgets:
            continue
        if re.search(r"\[\s*no fact", str(f.get("fact", "")), re.I):
            continue                          # placeholder, not a fact
        op = "forget" if f.get("still_true") is False else "update"
        item = {"op": op, "topic": f.get("topic", ""), "fact": f.get("fact", "")}
        if f.get("quote"):
            item["quote"] = str(f["quote"])
        ops.append(item)
    return ops


def extract_ops(model: str, memory_md: str, user_texts: List[str],
                base_url: Optional[str] = None, timeout: float = 90) -> List[Dict[str, Any]]:
    """Filter, ask the memory model, map to ops (not applied). Raises on
    backend errors. No model call when no message passes the filter."""
    from .ollama_client import chat_json

    texts = [t for t in (drop_others(strip_quoted(u)) for u in user_texts) if self_disclosing(t)]
    if not texts:
        return []
    out = chat_json(model, build_messages(memory_md, texts), FACTS_SCHEMA,
                    base_url=base_url, timeout=timeout, keep_alive=0)
    ops = facts_to_ops(out.get("facts") if isinstance(out, dict) else None)
    return grounded(reconcile(ops, memory_md), texts, memory_md)


# ── Grounding: drop what the user didn't actually say ────────────────────────

def grounded(ops: List[Dict[str, Any]], user_texts: List[str], memory_md: str) -> List[Dict[str, Any]]:
    """Keep ops the user's own words support. Small models copy prompt
    examples or invent facts; a fact sharing no content word with what the
    user wrote is dropped, and "forget" needs the user to mention the thing
    being forgotten."""
    from .memory_ops import fact_supported, names_supported, parse_memory, quote_in, _supported, _words

    said = _words(" ".join(user_texts))
    known = {e.topic.lower(): e.fact for e in parse_memory(memory_md)[1]}
    retracted = bool(_RETRACT.search(" ".join(user_texts)))
    kept, forgets = [], 0
    for op in ops:
        if op["op"] == "forget":
            # Forgetting is the destructive case, so it needs the user to say
            # something stopped ("no longer", "już nie", "sold"…) AND to name
            # what (a word of the remembered fact or its topic). At most one
            # per batch: a confused model can't wipe memory.
            topic = str(op.get("topic", ""))
            evidence = _words(known.get(topic.lower(), "")) | _words(topic)
            ok = retracted and _supported(evidence, said) and forgets == 0
            forgets += ok
        else:
            # Its words, or the user's words it quotes (any language) — and
            # no name or number the user didn't give.
            fact = op.get("fact", "")
            ok = ((fact_supported(fact, said) or quote_in(op.get("quote", ""), user_texts))
                  and names_supported(fact, user_texts))
        if ok:
            kept.append(op)
        else:
            log.info("memory: dropped ungrounded %s on %r", op["op"], op.get("topic"))
    return kept


# ── 3. Orchestration ─────────────────────────────────────────────────────────

def user_texts_since(messages: List[Dict[str, Any]], cursor: int) -> Tuple[List[str], int]:
    """User message texts after the first `cursor` user messages, plus the new
    cursor (the total number of user messages seen)."""
    users = [m for m in messages if m.get("role") == "user" and isinstance(m.get("content"), str)]
    return [m["content"] for m in users[cursor:]], len(users)


def resolve_model(chat_model: str = "") -> str:
    """The configured memory model, or the chat model when none is set."""
    from .config import config
    return (config.memory_model or "").strip() or chat_model


def memory_server() -> Optional[str]:
    """Ollama the memory model runs on (e.g. this PC's CPU), or None = the chat one."""
    from .config import config
    return (config.memory_ollama_url or "").strip() or None


def learn_from(messages: List[Dict[str, Any]], *, cursor: int = 0, chat_model: str = "",
               source: Optional[Dict[str, Any]] = None):
    """Learn from the user's messages after `cursor`. Returns (changes, cursor).
    Keeps the cursor when memory is off, so nothing is lost for later."""
    from .config import config
    from .memory import _read_memory
    from .memory_ops import apply_ops

    texts, new_cursor = user_texts_since(messages, cursor)
    if not texts:
        return [], new_cursor
    if not config.memory_enabled:
        return [], cursor
    model = resolve_model(chat_model)
    if not model:
        raise RuntimeError("no memory model configured")
    ops = extract_ops(model, _read_memory(), texts, base_url=memory_server())
    changes = apply_ops(ops, strict=True, source={**(source or {}), "memory_model": model})
    if changes:
        log.info("memory: learned %s", ", ".join(f"{c.op} {c.topic}" for c in changes))
    return changes, new_cursor
