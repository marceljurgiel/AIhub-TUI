"""
AIHub Tool: File operations (v0.1.0).
Provides read, write, and list operations for local files.
"""
import glob
import os


def read_file(path: str, max_lines: int = 200) -> str:
    """
    Read and return the contents of a local file.

    Args:
        path:      Path to the file (absolute or relative).
        max_lines: Maximum number of lines to return (default 200).

    Returns:
        File contents as a string (truncated if over max_lines),
        or an error message if the file cannot be read.
    """
    path = os.path.expanduser(path)
    if not os.path.exists(path):
        return f"[File Error] File not found: {path}"
    if os.path.isdir(path):
        return f"[File Error] Path is a directory: {path}"

    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
    except Exception as e:
        return f"[File Error] Could not read file: {e}"

    total = len(lines)
    truncated = lines[:max_lines]
    content = "".join(truncated)

    footer = ""
    if total > max_lines:
        footer = f"\n... [truncated: showing {max_lines} of {total} lines]"

    return f"```\n{content}{footer}\n```"


def write_file(path: str, content: str) -> str:
    """
    Write content to a local file, creating parent directories as needed.

    Args:
        path:    File path to write to.
        content: String content to write.

    Returns:
        Success or error message.
    """
    path = os.path.expanduser(path)
    try:
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        size = os.path.getsize(path)
        return f"[File OK] Written {size} bytes to: {path}"
    except Exception as e:
        return f"[File Error] Could not write file: {e}"


def list_files(directory: str, pattern: str = "*") -> str:
    """
    List files in a directory matching an optional glob pattern.

    Args:
        directory: Directory to list.
        pattern:   Glob pattern (default: '*' for all files).

    Returns:
        Newline-separated list of matching paths, or an error message.
    """
    directory = os.path.expanduser(directory)
    if not os.path.exists(directory):
        return f"[File Error] Directory not found: {directory}"
    if not os.path.isdir(directory):
        return f"[File Error] Not a directory: {directory}"

    search_pattern = os.path.join(directory, pattern)
    try:
        matches = sorted(glob.glob(search_pattern))
    except Exception as e:
        return f"[File Error] Glob pattern error: {e}"

    if not matches:
        return f"[No files matched '{pattern}' in {directory}]"

    lines = []
    for p in matches:
        if os.path.isdir(p):
            lines.append(f"  📁  {p}/")
        else:
            size = os.path.getsize(p)
            lines.append(f"  📄  {p}  ({size} bytes)")

    return "\n".join(lines)
