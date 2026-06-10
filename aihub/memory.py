"""
AIHub - Shared memory module.

Stores key facts and user preferences as a single human-readable Markdown file
at ~/.aihub/memory/memory.md. Memory is injected as a system message at the
start of each chat session and edited via slash-commands or the Memory modal.
"""
import os
import re
from datetime import datetime

from .config import MEMORY_DIR

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
            pass


def load_memory() -> str:
    """
    Load and return the memory Markdown string.
    Returns an empty string if no memory file exists yet.
    """
    _migrate_legacy()
    path = get_memory_path()
    if not os.path.exists(path):
        return ""
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read().strip()
    except Exception:
        return ""


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
    Add or update a keyed entry in the memory file.

    Entries are stored as:
        ## <key>
        <value>

    If a ## <key> section already exists it is replaced in-place;
    otherwise a new section is appended at the end.
    """
    content = load_memory()
    section_header = f"## {key}"

    # Build regex to find and replace the existing section
    pattern = re.compile(
        rf"^## {re.escape(key)}\s*\n(.*?)(?=\n## |\Z)",
        re.MULTILINE | re.DOTALL
    )

    new_section = f"{section_header}\n{value}\n"

    if pattern.search(content):
        content = pattern.sub(new_section, content)
    else:
        content = (content + "\n\n" + new_section).strip()

    # Add a metadata footer if not already present
    if "<!-- AIHub Memory File" not in content:
        ts = datetime.now().strftime("%Y-%m-%d")
        content = f"<!-- AIHub Memory File — created: {ts} -->\n\n" + content

    save_memory(content)


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
    "directly WITHOUT calling any tool."
)


def build_system_prompt() -> str:
    """
    Return the system message: a base operating instruction (always present),
    followed by the shared memory when enabled and non-empty. Never empty.
    """
    from .config import config
    prompt_parts = [_BASE_PROMPT]

    if config.memory_enabled:
        mem = load_memory()
        if mem:
            prompt_parts.append(
                "You have the following memory about this user and previous "
                "sessions. Use this information to personalize your responses:\n\n"
                + mem
            )

    return "\n\n".join(prompt_parts)


def extract_and_update_memory(model_name: str, messages: list) -> str:
    """
    Extract key facts from the conversation using `model_name` and append them
    to the shared memory. Returns the extracted summary or an error message.
    """
    from .ollama_client import chat_sync, is_ollama_running

    if not is_ollama_running():
        return "Error: Ollama is not running."

    # Prepare the messages for summarization (ignore system messages)
    chat_history = [m for m in messages if m.get("role") in ("user", "assistant") and m.get("content")]
    if not chat_history:
        return "Error: No conversation history to extract from."

    # Format the history for the model (last 30 messages for depth)
    formatted_history = ""
    for m in chat_history[-30:]:
        role = "User" if m["role"] == "user" else "Assistant"
        formatted_history += f"{role}: {m['content']}\n"

    prompt = (
        "Instructions: Extract the most important facts, user preferences, and key information "
        "from the conversation below. Focus on long-term useful information. "
        "Be concise. Format the output as a clean Markdown list of facts.\n\n"
        "### CONVERSATION HISTORY:\n" + formatted_history + "\n\n"
        "### EXTRACTED KEY FACTS:"
    )

    summary = chat_sync(model_name, [{"role": "user", "content": prompt}], temperature=0.3)

    if summary and not summary.startswith("Error:"):
        summary = summary.strip()
        # Timestamped key so successive extractions don't overwrite each other.
        ts = datetime.now().strftime("%Y-%m-%d %H:%M")
        update_memory_entry(f"Facts Extracted on {ts}", summary)
        return summary
    else:
        return f"Error: Model failed to generate summary. {summary}"
