"""
AIHub - Per-model memory module (v0.1.0).
Stores key facts, user preferences, and session context as human-readable
Markdown files at ~/.aihub/memory/<model_name>.md.

Memory is injected as a system message at the start of each chat session
and can be updated with slash-commands during chat.
"""
import os
import re
from datetime import datetime

from .config import MEMORY_DIR


def _sanitize(name: str) -> str:
    """Convert a model name to a safe filename (replace / and : with _)."""
    return re.sub(r"[^\w\-.]", "_", name)


def get_memory_path(model_name: str) -> str:
    """Return the full path to the memory .md file for a given model."""
    return os.path.join(MEMORY_DIR, f"{_sanitize(model_name)}.md")


def load_memory(model_name: str) -> str:
    """
    Load and return the memory Markdown string for a model.
    Returns an empty string if no memory file exists yet.
    """
    path = get_memory_path(model_name)
    if not os.path.exists(path):
        return ""
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read().strip()
    except Exception:
        return ""


def save_memory(model_name: str, content: str) -> None:
    """
    Overwrite the entire memory file with the given Markdown content.
    Creates the memory directory if it doesn't exist.
    """
    os.makedirs(MEMORY_DIR, exist_ok=True)
    path = get_memory_path(model_name)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content.strip() + "\n")


def update_memory_entry(model_name: str, key: str, value: str) -> None:
    """
    Add or update a keyed entry in the memory file.

    Entries are stored as:
        ## <key>
        <value>

    If a ## <key> section already exists it is replaced in-place;
    otherwise a new section is appended at the end.
    """
    content = load_memory(model_name)
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
        content = (
            f"<!-- AIHub Memory File — model: {model_name} | created: {ts} -->\n\n"
            + content
        )

    save_memory(model_name, content)


def clear_memory(model_name: str) -> bool:
    """
    Delete the memory file for a model.
    Returns True if the file existed and was deleted, False otherwise.
    """
    path = get_memory_path(model_name)
    if os.path.exists(path):
        os.remove(path)
        return True
    return False


def build_system_prompt(model_name: str) -> str:
    """
    Return a system message string that injects memory into the chat context.
    Returns an empty string if there is no memory for this model.
    """
    from .config import config
    prompt_parts = []
    
    if config.global_memory_enabled:
        g_mem = load_memory("global")
        if g_mem:
            prompt_parts.append(f"--- Global Memory ---\n{g_mem}")
            
    m_mem = load_memory(model_name)
    if m_mem:
        prompt_parts.append(f"--- Model Memory ({model_name}) ---\n{m_mem}")
        
    if not prompt_parts:
        return ""
        
    combined = "\n\n".join(prompt_parts)
    return (
        "You have the following memory about this user and previous sessions. "
        "Use this information to personalize your responses:\n\n"
        + combined
    )


def extract_and_update_memory(model_name: str, messages: list, target: str = "chat") -> str:
    """
    Extract key facts from the conversation using the model and save to memory.
    target: 'chat' (model-specific) or 'global'.
    Returns the extracted summary string or an error message.
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
        # Clean up the summary (remove potential model yapping)
        summary = summary.strip()
        memory_target = model_name if target == "chat" else "global"
        
        # Use a timestamped key to avoid overwriting all previous summaries
        ts = datetime.now().strftime("%Y-%m-%d %H:%M")
        key = f"Facts Extracted on {ts}"
        update_memory_entry(memory_target, key, summary)
        return summary
    else:
        return f"Error: Model failed to generate summary. {summary}"
