"""AIHub TUI — background workers.

Workers run in @work(thread=True) and ONLY post messages back to the UI
thread. They never hold or mutate widget references — that's the fix for
the cross-thread race that crashed the old tui.py.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional


def stream_chat(
    screen,
    model_name: str,
    messages: List[Dict[str, Any]],
    *,
    temperature: float,
    context_length: int,
    tools_enabled: bool,
    stream_fn=None,
) -> None:
    """Drive `run_chat_turn` and forward every event as a ChatEventReceived.

    Runs in a worker thread. The screen's `on_chat_event_received` handler
    runs on the UI thread and mutates the ChatLog.

    `Done` is always posted last, even on exception, so the UI can re-enable
    the input.
    """
    from ..chat import Done, Error, run_chat_turn
    from .messages import ChatEventReceived

    final_text = ""
    try:
        for event in run_chat_turn(
            model_name, messages,
            temperature=temperature,
            context_length=context_length,
            tools_enabled=tools_enabled,
            stream_fn=stream_fn,
        ):
            # Capture final text so the Done event in `finally` is meaningful
            # even if the engine itself didn't emit a Done (it should, but
            # belt-and-braces in case of mid-stream exception).
            try:
                if event.__class__.__name__ == "Done":
                    final_text = event.final_text
            except Exception:
                pass
            screen.post_message(ChatEventReceived(event))
            if event.__class__.__name__ == "Done":
                return
            if event.__class__.__name__ == "Error" and event.fatal:
                return
    except Exception as exc:
        screen.post_message(ChatEventReceived(Error(message=f"Worker crashed: {exc}", fatal=True)))
    finally:
        # Belt-and-braces — only fires if the loop above didn't already exit
        # via Done/fatal-Error.
        screen.post_message(ChatEventReceived(Done(final_text=final_text)))


def poll_backends(screen) -> None:
    """Poll both Ollama and llama.cpp status; post status messages."""
    from ..ollama_client import is_ollama_running
    from .messages import OllamaStatusChanged, LlamaCppStatusChanged
    from ..config import config

    screen.post_message(OllamaStatusChanged(online=bool(is_ollama_running())))

    if config.llamacpp_enabled:
        from ..llamacpp_client import is_llamacpp_running, get_loaded_model
        ok = bool(is_llamacpp_running())
        model = get_loaded_model() if ok else ""
        screen.post_message(LlamaCppStatusChanged(online=ok, model_name=model))


# Keep old name as alias so any external callers don't break.
poll_ollama = poll_backends


def extract_memory(screen, model_name: str, messages, target: str) -> None:
    """Run memory.extract_and_update_memory in a worker; report via SystemBubble."""
    from ..memory import extract_and_update_memory
    from .messages import MemoryUpdated, ChatEventReceived
    from ..chat import Error
    try:
        outcome = extract_and_update_memory(model_name, messages, target=target)
    except Exception as exc:
        screen.post_message(ChatEventReceived(Error(
            message=f"Memory extraction failed: {exc}", fatal=False,
        )))
        return
    screen.post_message(MemoryUpdated(model_name=model_name, summary=outcome))
