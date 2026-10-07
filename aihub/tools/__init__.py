"""
AIHub Tools Package (v0.1.0).
Provides a modular tool-calling system for agentic chat sessions.

Tools are registered in TOOLS_REGISTRY and described in TOOLS_SCHEMA
(Ollama function-calling format). The run_tool() dispatcher executes
the requested tool and returns the result as a string.
"""
import re

from .terminal    import run_terminal
from .file_ops    import read_file, write_file, edit_file, list_files
from .web_search  import search_web
from .file_search import search_files
from .remember    import remember


def use_skill(skill: str) -> str:
    from ..skills import use_skill as _use
    return _use(skill)


def search_knowledge(query: str, base: str = "") -> str:
    from ..knowledge import search_knowledge as _search
    return _search(query, base)

# ── Tool registry: name → Python callable ────────────────────────────────────
TOOLS_REGISTRY = {
    "run_terminal":  run_terminal,
    "read_file":     read_file,
    "write_file":    write_file,
    "edit_file":     edit_file,
    "list_files":    list_files,
    "search_web":    search_web,
    "search_files":  search_files,
    "remember":      remember,
    "use_skill":     use_skill,
    # Offered only when a knowledge base is attached (agent kb:<name>, /kb);
    # its schema is built per turn by knowledge.tool_schema.
    "search_knowledge": search_knowledge,
}

# ── Tool schema (Ollama / OpenAI function-calling format) ─────────────────────
TOOLS_SCHEMA = [
    {
        "type": "function",
        "function": {
            "name":        "use_skill",
            "description": "Load a skill's instructions (see the Skills list in the system prompt). Call it first when the request matches a skill, then follow what it returns.",
            "parameters": {
                "type": "object",
                "properties": {
                    "skill": {"type": "string", "description": "The skill's name from the Skills list."}
                },
                "required": ["skill"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name":        "remember",
            "description": "Save a lasting fact about the user to memory (their preferences, setup, names, projects) so it is known in future chats. Call this whenever the user asks you to remember something or states a durable preference — never say you saved something without calling it. Not for temporary details of the current task.",
            "parameters": {
                "type": "object",
                "properties": {
                    "topic": {
                        "type":        "string",
                        "description": "Short heading, e.g. 'Editor'. A new fact for an existing topic is added to it; it replaces the old one only when it says what changed (e.g. 'now uses Helix instead of Neovim')."
                    },
                    "fact": {
                        "type":        "string",
                        "description": "The fact to remember, e.g. 'Favourite editor is Neovim'."
                    }
                },
                "required": ["topic", "fact"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name":        "run_terminal",
            "description": "Execute a shell command and return the output. Use for real terminal operations (git, build, tests, package managers). Do NOT use it for file operations — use read_file/write_file/edit_file/search_files/list_files instead. Keep commands non-interactive.",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {
                        "type":        "string",
                        "description": "The shell command to execute."
                    },
                    "timeout": {
                        "type":        "integer",
                        "description": "Timeout in seconds (default 30).",
                        "default":     30
                    }
                },
                "required": ["command"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name":        "read_file",
            "description": "Read and return the contents of a local file.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type":        "string",
                        "description": "Absolute or relative path to the file."
                    },
                    "max_lines": {
                        "type":        "integer",
                        "description": "Maximum number of lines to return (default 200).",
                        "default":     200
                    }
                },
                "required": ["path"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name":        "write_file",
            "description": "Create a new file (or replace a file's whole content) with the given content. Use this whenever the user asks to save or create a file. For a small change inside a file that already exists, edit_file is better. Never proactively create documentation/README files unless asked.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type":        "string",
                        "description": "Path to the file to write."
                    },
                    "content": {
                        "type":        "string",
                        "description": "Content to write into the file."
                    }
                },
                "required": ["path", "content"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name":        "edit_file",
            "description": "Change part of a file that ALREADY EXISTS by replacing an exact string. It cannot create files — use write_file to create or save a new file. The 'old' text must appear exactly once (include surrounding context to make it unique).",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type":        "string",
                        "description": "Path to the file to edit."
                    },
                    "old": {
                        "type":        "string",
                        "description": "Exact text to find (must be unique in the file)."
                    },
                    "new": {
                        "type":        "string",
                        "description": "Replacement text."
                    }
                },
                "required": ["path", "old", "new"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name":        "list_files",
            "description": "List files in a directory, optionally filtered by glob pattern.",
            "parameters": {
                "type": "object",
                "properties": {
                    "directory": {
                        "type":        "string",
                        "description": "Directory to list."
                    },
                    "pattern": {
                        "type":        "string",
                        "description": "Glob pattern filter (e.g. '*.py'). Default: '*'.",
                        "default":     "*"
                    }
                },
                "required": ["directory"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name":        "search_web",
            "description": "Search the web using DuckDuckGo and return the top results.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type":        "string",
                        "description": "Search query."
                    },
                    "num_results": {
                        "type":        "integer",
                        "description": "Number of results to return (default 5).",
                        "default":     5
                    }
                },
                "required": ["query"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name":        "search_files",
            "description": "Search for files by name (glob) or content (grep) in a directory.",
            "parameters": {
                "type": "object",
                "properties": {
                    "root": {
                        "type":        "string",
                        "description": "Root directory to search from."
                    },
                    "pattern": {
                        "type":        "string",
                        "description": "Glob pattern to match filenames (e.g. '*.py')."
                    },
                    "content_query": {
                        "type":        "string",
                        "description": "Optional substring to grep inside matched files.",
                        "default":     ""
                    }
                },
                "required": ["root", "pattern"]
            }
        }
    },
]


# ── Tool-intent gate ──────────────────────────────────────────────────────────
# Plain chat offers tools only when the latest user message plausibly needs
# one, so small models don't fire tools during ordinary conversation. Matching
# is on whole words and concrete shapes (paths, file names, URLs, commands) —
# a bare substring list matched "run" in "running late", "/" in "2/3" and
# "list" in "a list of fruits", and offered tools to half of all chit-chat.
# Mutating tools still need the user's approval, so a false positive costs a
# spurious offer, not an action. Tune the patterns below.

_EXT = (r"py|js|ts|tsx|jsx|json|md|txt|csv|log|sh|ya?ml|toml|ini|cfg|conf|env|"
        r"html|css|rs|go|java|kt|c|cpp|h|hpp|rb|php|sql|xml|lock|pdf")

_TOOL_INTENT_PATTERNS = [re.compile(p, re.IGNORECASE) for p in (
    # URLs, paths and file names
    r"https?://",
    r"(?:^|[\s\"'`(])(?:~|\.{1,2})/",                        # ~/x  ./x  ../x
    r"(?:^|[\s\"'`(])/[\w.-]+/[\w.-]+",                      # /etc/hostname
    rf"\b[\w-]+\.(?:{_EXT})\b",                              # notes.txt, App.tsx
    # files and the filesystem
    r"\b(?:files?|folders?|director(?:y|ies)|repo(?:sitory)?|codebase)\b",
    r"\b(?:disk|free) space\b|\b(?:cpu|memory|ram|gpu) usage\b|\bprocesses\b",
    # shell / commands
    r"\b(?:terminal|shell|command line|bash|zsh)\b",
    r"\b(?:run|execute|launch)\b.{0,30}\b(?:commands?|scripts?|tests?|test suite|"
    r"programs?|code|build|ls|git|npm|pnpm|bun|pip|python3?|make|cargo|docker|pytest)\b",
    r"\b(?:git|grep|npm|pnpm|pip|docker|cargo|pytest|mkdir|chmod|ls|df|du)\b\s+\S",
    r"`[^`]+`",                                              # an inline command
    # web and live information
    r"\b(?:search|look)\b.{0,15}\b(?:web|internet|online)\b|\blook up\b|\bgoogle\b",
    r"\bweather\b|\bnews\b|\bstock price\b|\bexchange rate\b|\blatest\b.{0,30}\b(?:release|version)\b",
    r"\bwebsite\b|\bweb ?page\b",
    # Polish
    r"\bplik(?:i|u|ów|ach|iem)?\b|\bkatalog(?:u|i|ach)?\b|\bfolder(?:ze|a|y)?\b",
    r"\buruchom\w*|\bwykonaj\w*|\bpolecen\w*|\bkomend\w*|\bskrypt\w*|\bterminal\w*",
    r"\bwyszukaj\w*|\bw internecie\b|\bw sieci\b|\bpogod\w*|\bwiadomości\b|\bkurs\w* walut",
    r"\bprzeczytaj\w*|\botwórz\w*|\bzapisz\w*|\busuń\w*|\bedytuj\w*",
    # memory
    r"\bremember\b|\bmemori[sz]e\b|\bdon'?t forget\b",
    r"\bzapami[eę]taj\w*|\bpami[eę]taj\w*|\bnie zapomnij\b|\bw pamięci\b",
)]


def wants_tools(messages: list) -> bool:
    """
    Heuristic: may the latest user turn need a tool?

    True when the latest user message matches a tool-intent pattern, or when
    the previous exchange already used tools (so a follow-up like "yes, run
    it" or "now the next one" keeps them). Used to withhold the tools schema
    during plain conversation so models don't fire tools spuriously.
    """
    msgs = messages or []
    last_user_idx = next(
        (i for i in range(len(msgs) - 1, -1, -1) if msgs[i].get("role") == "user"), None)
    if last_user_idx is None:
        return False
    content = msgs[last_user_idx].get("content", "")
    text = content if isinstance(content, str) else str(content)
    if any(p.search(text) for p in _TOOL_INTENT_PATTERNS):
        return True
    try:
        from ..skills import relevant
        if relevant(text):
            return True
    except Exception:
        pass
    try:
        from ..mcp_client import servers_for
        if servers_for(text):
            return True
    except Exception:
        pass
    # Follow-up: did the assistant use tools since the previous user message?
    for m in reversed(msgs[:last_user_idx]):
        if m.get("role") == "user":
            break
        if m.get("role") == "tool" or m.get("tool_calls"):
            return True
    return False


def without_unused(schema: list) -> list:
    """Drop use_skill when there are no enabled skills to load."""
    if not any(t.get("function", {}).get("name") == "use_skill" for t in schema or []):
        return schema
    try:
        from ..skills import enabled_skills
        if enabled_skills():
            return schema
    except Exception:
        pass
    return [t for t in schema if t.get("function", {}).get("name") != "use_skill"]


# Agent mode uses the full tool set (including edit_file). Kept as a distinct
# name so chat and agent tool surfaces can diverge later.
AGENT_TOOLS_SCHEMA = TOOLS_SCHEMA


import threading

# What the user said in the current turn's conversation (set by the chat
# loop, per thread), so `remember` can refuse facts the user never stated.
_turn = threading.local()


def set_user_text(text):
    _turn.user_text = text


def user_text():
    return getattr(_turn, "user_text", None)


def _fit_arguments(fn, kwargs: dict) -> dict:
    """Small models send numbers as strings ("10"), booleans as "true", and
    extra parameters the tool doesn't have. Convert to the annotated types
    and drop unknown names, instead of failing the whole call."""
    import inspect
    try:
        params = inspect.signature(fn).parameters
    except (TypeError, ValueError):
        return kwargs
    out = {}
    for key, value in kwargs.items():
        p = params.get(key)
        if p is None:
            continue
        ann = p.annotation if p.annotation is not inspect.Parameter.empty else (
            type(p.default) if p.default is not inspect.Parameter.empty and p.default is not None else None)
        if isinstance(ann, str):
            ann = {"int": int, "float": float, "bool": bool, "str": str}.get(ann)
        try:
            if ann is bool and isinstance(value, str):
                value = value.strip().lower() in ("true", "1", "yes", "on")
            elif ann in (int, float) and isinstance(value, str):
                value = ann(float(value.strip()))
            elif ann is int and isinstance(value, float):
                value = int(value)
            elif ann is str and isinstance(value, (int, float)) and not isinstance(value, bool):
                value = str(value)
        except ValueError:
            pass                      # leave it; the tool reports the problem
        out[key] = value
    # One required text parameter missing (search_web without "query") but
    # other values given — models invent {"genre": …, "platforms": […]}:
    # build it from those values rather than failing the call.
    required = [n for n, p in params.items() if p.default is inspect.Parameter.empty]
    missing = [n for n in required if n not in out]
    if len(missing) == 1 and len(required) == 1 and kwargs:
        parts = []
        for v in kwargs.values():
            parts += [str(x) for x in v] if isinstance(v, (list, tuple)) else [str(v)]
        text = " ".join(p for p in parts if p and p.lower() not in ("none", "null", "true", "false"))
        if text:
            out[missing[0]] = text
    return out


def _signature_hint(fn) -> str:
    import inspect
    try:
        return ", ".join(
            f"{n}{'' if p.default is inspect.Parameter.empty else ' (optional)'}"
            for n, p in inspect.signature(fn).parameters.items())
    except (TypeError, ValueError):
        return "?"


def run_tool(name: str, **kwargs) -> str:
    """
    Dispatch a tool call by name and return the result as a string.

    Args:
        name:    Tool name (must be in TOOLS_REGISTRY).
        **kwargs: Arguments forwarded to the tool function.

    Returns:
        String output from the tool, or an error message.
    """
    if name not in TOOLS_REGISTRY:
        from .. import mcp_client
        if mcp_client.split_name(name):
            return mcp_client.run(name, kwargs)
        return f"[Tool Error] Unknown tool: '{name}'. Available: {list(TOOLS_REGISTRY)}"
    try:
        kwargs = _fit_arguments(TOOLS_REGISTRY[name], kwargs)
        return str(TOOLS_REGISTRY[name](**kwargs))
    except TypeError as e:
        return (f"[Tool Error] Bad arguments for '{name}': {e}. "
                f"It takes: {_signature_hint(TOOLS_REGISTRY[name])}. Call it again with those.")
    except Exception as e:
        return f"[Tool Error] '{name}' failed: {e}"


def get_tools_description() -> str:
    """Return a human-readable summary of all available tools."""
    lines = []
    for schema in TOOLS_SCHEMA:
        fn = schema["function"]
        lines.append(f"  • {fn['name']}: {fn['description']}")
    return "\n".join(lines)
