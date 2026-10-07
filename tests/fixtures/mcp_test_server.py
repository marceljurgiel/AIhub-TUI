"""A tiny stdio MCP server for AIhub's tests: two read-only tools, one that
changes something, one that fails."""
import sys

from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations

server = MCPServer("notes")
NOTES = {"shopping": "milk, bread", "ideas": "AIhub MCP support"}


@server.tool(annotations=ToolAnnotations(readOnlyHint=True))
def list_notes() -> str:
    """List the titles of all notes."""
    return ", ".join(sorted(NOTES))


@server.tool(annotations=ToolAnnotations(readOnlyHint=True))
def read_note(title: str) -> str:
    """Read one note by its title."""
    if title not in NOTES:
        raise ValueError(f"no note called {title!r}")
    return NOTES[title]


@server.tool(annotations=ToolAnnotations(destructiveHint=True))
def delete_note(title: str) -> str:
    """Delete a note."""
    NOTES.pop(title, None)
    return f"deleted {title}"


@server.tool()
def add_note(title: str, text: str, pinned: bool = False) -> str:
    """Create a note (no annotations: treated as changing)."""
    NOTES[title] = text
    return f"saved {title} (pinned={pinned})"


if __name__ == "__main__":
    server.run("stdio")
