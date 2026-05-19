"""
AIHub - Per-model chat history module (v0.1.0).
Persists chat sessions as JSON files at:
    ~/.aihub/history/<model_name>/YYYY-MM-DD_HH-MM-SS.json

Each file stores the messages list plus metadata (model, temperature,
start/end timestamps, message count).
"""
import json
import os
import re
from datetime import datetime
from typing import Optional

from .config import HISTORY_DIR, config


def _sanitize(name: str) -> str:
    """Convert a model name to a safe directory name."""
    return re.sub(r"[^\w\-.]", "_", name)


def get_history_dir(model_name: str) -> str:
    """Return the path to the history directory for a specific model."""
    return os.path.join(HISTORY_DIR, _sanitize(model_name))


def save_session(
    model_name: str,
    messages: list,
    temperature: float = 0.7,
    start_time: Optional[datetime] = None,
) -> str:
    """
    Save a chat session to disk as a timestamped JSON file.

    Args:
        model_name:  Name of the model used.
        messages:    The full messages list (role/content dicts).
        temperature: Temperature setting used in the session.
        start_time:  Session start datetime (defaults to now).

    Returns:
        Absolute path to the saved session file, or "" on failure.
    """
    if not messages:
        return ""

    # Filter to only user/assistant messages (exclude system/tool)
    user_turns = [m for m in messages if m.get("role") in ("user", "assistant")]
    if not user_turns:
        return ""

    model_dir = get_history_dir(model_name)
    os.makedirs(model_dir, exist_ok=True)

    end_time = datetime.now()
    _start   = start_time or end_time
    filename = _start.strftime("%Y-%m-%d_%H-%M-%S") + ".json"
    filepath = os.path.join(model_dir, filename)

    session_data = {
        "model":       model_name,
        "temperature": temperature,
        "start_time":  _start.isoformat(),
        "end_time":    end_time.isoformat(),
        "message_count": len(user_turns),
        "messages":    messages,  # save full messages including system/tool
    }

    try:
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(session_data, f, ensure_ascii=False, indent=2)

        # Prune old sessions if over limit
        _prune_old_sessions(model_name)
        return filepath
    except Exception:
        return ""


def list_sessions(model_name: str) -> list:
    """
    Return metadata about all saved sessions for a model, newest-first.

    Each entry is a dict with keys:
        filename, model, start_time, end_time, message_count, temperature
    """
    model_dir = get_history_dir(model_name)
    if not os.path.exists(model_dir):
        return []

    sessions = []
    try:
        for fname in sorted(os.listdir(model_dir), reverse=True):
            if not fname.endswith(".json"):
                continue
            fpath = os.path.join(model_dir, fname)
            try:
                with open(fpath, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if not isinstance(data, dict):
                    continue
                sessions.append({
                    "filename":      fname,
                    "filepath":      fpath,
                    "model":         data.get("model", model_name),
                    "start_time":    data.get("start_time", ""),
                    "end_time":      data.get("end_time", ""),
                    "message_count": data.get("message_count", 0),
                    "temperature":   data.get("temperature", 0.7),
                })
            except (json.JSONDecodeError, IOError, ValueError, TypeError):
                continue
    except OSError:
        pass
    return sessions


def load_session(model_name: str, filename: str) -> list:
    """
    Load and return the messages list from a saved session file.
    Returns an empty list on any error.
    """
    model_dir = get_history_dir(model_name)
    if not model_dir or not os.path.exists(model_dir):
        return []
    
    fpath = os.path.join(model_dir, filename)
    if not os.path.exists(fpath):
        return []
        
    try:
        with open(fpath, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data.get("messages", []) if isinstance(data, dict) else []
    except (json.JSONDecodeError, IOError, TypeError, ValueError) as e:
        return []


def delete_session(model_name: str, filename: str) -> bool:
    """
    Delete a saved session file.
    Returns True if deleted, False if it didn't exist or failed.
    """
    fpath = os.path.join(get_history_dir(model_name), filename)
    if os.path.exists(fpath):
        try:
            os.remove(fpath)
            return True
        except Exception:
            return False
    return False


def _prune_old_sessions(model_name: str) -> None:
    """Remove oldest session files when the count exceeds the max limit."""
    model_dir = get_history_dir(model_name)
    files = sorted(
        [f for f in os.listdir(model_dir) if f.endswith(".json")]
    )
    max_sessions = config.max_history_sessions
    while len(files) > max_sessions:
        oldest = files.pop(0)
        try:
            os.remove(os.path.join(model_dir, oldest))
        except Exception:
            pass
