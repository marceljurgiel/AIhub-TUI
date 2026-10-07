"""
AIHub - Shared memory module.

Stores key facts and user preferences as a single human-readable Markdown file
at ~/.aihub/memory/memory.md. Memory is injected as a system message at the
start of each chat session and edited via slash-commands or the Memory modal.
"""
import logging
import os
import re
from datetime import datetime

from .config import MEMORY_DIR

log = logging.getLogger(__name__)

# On-disk filename for the single shared memory store.
_MEMORY_FILE = "memory.md"


def get_memory_path() -> str:
    """Return the full path to the shared memory .md file."""
    return os.path.join(MEMORY_DIR, _MEMORY_FILE)


def _migrate_legacy() -> None:
    """One-time: adopt the old 'global.md' store as the shared memory file."""
    new = get_memory_path()
    if os.path.exists(new):
        return
    legacy = os.path.join(MEMORY_DIR, "global.md")
    if os.path.exists(legacy):
        try:
            os.replace(legacy, new)
        except Exception:
            log.warning("could not migrate legacy memory file %s", legacy, exc_info=True)


def load_memory() -> str:
    """
    Load and return the memory Markdown string.
    Returns an empty string if no memory file exists yet.
    """
    try:
        return _read_memory()
    except Exception:
        # Display paths (system prompt, status) degrade to "no memory" —
        # but writers use _read_memory() directly so they never mistake an
        # unreadable file for an empty one.
        log.warning("could not read memory file %s", get_memory_path(), exc_info=True)
        return ""


def _read_memory() -> str:
    """Memory contents; "" only when the file doesn't exist. Read errors
    (bad encoding, permissions) raise."""
    _migrate_legacy()
    path = get_memory_path()
    if not os.path.exists(path):
        return ""
    with open(path, "r", encoding="utf-8") as f:
        return f.read().strip()


def save_memory(content: str) -> None:
    """
    Overwrite the entire memory file with the given Markdown content.
    Creates the memory directory if it doesn't exist.
    """
    os.makedirs(MEMORY_DIR, exist_ok=True)
    _migrate_legacy()
    with open(get_memory_path(), "w", encoding="utf-8") as f:
        f.write(content.strip() + "\n")


def update_memory_entry(key: str, value: str) -> None:
    """
    Add or update a keyed entry ("## <key>" + value) in the memory file — the
    user's own `/memory save`. Goes through memory_ops so it's recorded in
    the change log like every other write; not secret-filtered (the user
    typed it on purpose).

    Raises if the existing file can't be read: rewriting it from an empty
    string would replace the user's whole memory with this one entry.
    """
    from .memory_ops import apply_ops
    apply_ops([{"op": "update", "topic": key, "fact": value}], strict=False, source={"by": "user"})


def clear_memory() -> bool:
    """
    Delete the memory file.
    Returns True if the file existed and was deleted, False otherwise.
    """
    path = get_memory_path()
    if os.path.exists(path):
        os.remove(path)
        return True
    return False


def memory_present() -> bool:
    """True if memory is enabled and has content (drives the status indicator)."""
    from .config import config
    return bool(config.memory_enabled) and bool(load_memory())


_BASE_PROMPT = (
    "You are AIHub's assistant, running in a terminal chat interface for local AI models. "
    "Be concise and direct; answer in plain text suitable for a terminal.\n"
    "If tools are available to you (running shell commands, reading/writing/searching files, "
    "web search), use a tool ONLY when the user's request clearly requires it — e.g. they ask "
    "you to run something, inspect or modify files, or look up live information. For general "
    "conversation, explanations, or anything you can answer from your own knowledge, respond "
    "directly WITHOUT calling any tool. Exception — skills: when the user invokes a skill or "
    "the request matches one, DO use the tools its steps name (e.g. run git before writing a "
    "commit message) instead of guessing.\n"
    "Report tool results truthfully. A result starting with an [... Error] tag, a non-zero "
    "[Exit: N], or [Denied by user] means the action did NOT happen: say so plainly, with the "
    "reason given in the result. Never claim a file was written or a command ran unless its "
    "result confirms it, and never invent other reasons such as security restrictions."
)


def build_system_prompt(base: str = "") -> str:
    """
    Return the system message: `base` (the chat instructions by default, or an
    agent prompt), the environment, and the shared memory when enabled and
    non-empty. Never empty.
    """
    from .config import config
    from .tools.workdir import environment_info
    prompt_parts = [base or _BASE_PROMPT, environment_info()]

    if config.memory_enabled:
        mem = load_memory()
        if mem:
            prompt_parts.append(
                "Memory — facts about the user from earlier sessions. Use them "
                "whenever they're relevant (their name, setup, preferences, "
                "projects, servers…) instead of asking again, but don't recite "
                "them unprompted. If the user asks what you know or remember "
                "about them, answer from this:\n\n" + mem
            )

    return "\n\n".join(prompt_parts)


def extract_and_update_memory(model_name: str, messages: list) -> str:
    """
    `/memoryadd`: learn from the whole conversation now, with the memory model
    (see memory_learn) — whatever backend the chat used. Returns a summary of
    what changed, or an "Error: …" message.
    """
    from .config import config
    from .memory_learn import learn_from

    if not config.memory_enabled:
        return "Error: memory is turned off in Settings."
    try:
        changes, _ = learn_from(messages, cursor=0, chat_model=model_name, source={"by": "memoryadd"})
    except Exception as exc:
        return f"Error: {exc}"
    if not changes:
        return "Nothing new to remember."
    return "\n".join(f"- {c.topic}: {c.after}" if c.after else f"- forgot {c.topic}" for c in changes)
