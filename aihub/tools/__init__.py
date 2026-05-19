"""
AIHub Tools Package (v0.1.0).
Provides a modular tool-calling system for agentic chat sessions.

Tools are registered in TOOLS_REGISTRY and described in TOOLS_SCHEMA
(Ollama function-calling format). The run_tool() dispatcher executes
the requested tool and returns the result as a string.
"""
from .terminal    import run_terminal
from .file_ops    import read_file, write_file, list_files
from .web_search  import search_web
from .file_search import search_files

# ── Tool registry: name → Python callable ────────────────────────────────────
TOOLS_REGISTRY = {
    "run_terminal":  run_terminal,
    "read_file":     read_file,
    "write_file":    write_file,
    "list_files":    list_files,
    "search_web":    search_web,
    "search_files":  search_files,
}

# ── Tool schema (Ollama / OpenAI function-calling format) ─────────────────────
TOOLS_SCHEMA = [
    {
        "type": "function",
        "function": {
            "name":        "run_terminal",
            "description": "Execute a shell command and return the output. Use for system tasks, running scripts, checking files, etc.",
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
            "description": "Write content to a local file (creates it if it doesn't exist).",
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
        return f"[Tool Error] Unknown tool: '{name}'. Available: {list(TOOLS_REGISTRY)}"
    try:
        return str(TOOLS_REGISTRY[name](**kwargs))
    except TypeError as e:
        return f"[Tool Error] Bad arguments for '{name}': {e}"
    except Exception as e:
        return f"[Tool Error] '{name}' failed: {e}"


def get_tools_description() -> str:
    """Return a human-readable summary of all available tools."""
    lines = []
    for schema in TOOLS_SCHEMA:
        fn = schema["function"]
        lines.append(f"  • {fn['name']}: {fn['description']}")
    return "\n".join(lines)
