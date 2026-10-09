"""
AIHub Tool: remember — save a lasting fact about the user to memory.

Without it a model asked to "remember" something would reply that it did,
while nothing was stored. Facts go into the same memory file the Memory
modal edits and that is injected into every system prompt.
"""


def remember(topic: str, fact: str) -> str:
    """
    Save (or update) a fact in memory under a short topic heading.

    Args:
        topic: A short heading, e.g. "Editor" or "Favourite language".
               A topic that already exists is replaced with the new fact.
        fact:  The fact itself, e.g. "Uses Neovim".

    Returns:
        Confirmation, or a [Memory Error] message.
    """
    from ..config import config

    if not config.memory_enabled:
        return ("[Memory Error] Memory is turned off in Settings, so nothing was "
                "saved. Tell the user they can turn it on in Settings (F3).")
    from ..memory_ops import apply_ops, looks_secret

    topic = " ".join(str(topic).split())[:60]
    fact = str(fact).strip()
    if not topic or not fact:
        return "[Memory Error] Both a topic and a fact are needed."
    from . import user_text
    from ..memory_ops import fact_supported, _words
    said = user_text()
    # Small models "remember" things nobody said (search results, guesses,
    # facts already in memory). Only what the user's own words support.
    if said is not None and not fact_supported(fact, _words(said)):
        return ("[Memory Error] Not saved: the user didn't say this. Only remember "
                "facts the user states about themself in this conversation — "
                "don't save search results or guesses.")
    if looks_secret(f"{topic} {fact}"):
        return ("[Memory Error] That looks like a secret (password, key, token…); "
                "memory never stores those. Tell the user it wasn't saved.")
    try:
        changes = apply_ops([{"op": "update", "topic": topic, "fact": fact}],
                            strict=True, source={"by": "remember"})
    except Exception as exc:
        return f"[Memory Error] Could not save to memory: {exc}"
    if not changes:
        return f"[Memory OK] Already known: {fact}"
    return f"[Memory OK] Saved under \"{changes[0].topic}\": {fact}"
