"""
AIHub Tool: Terminal access (v0.1.0).
Executes shell commands and returns the combined stdout+stderr output.
Includes a basic safety check for destructive commands.
"""
import subprocess

# Commands that are considered potentially destructive — user will see a warning
_DANGEROUS_PREFIXES = (
    "rm ", "rm\t", "rmdir", "dd ", "mkfs", "format ",
    "shred", "fdisk", "parted", "> /dev/", ":(){ :",
)


def run_terminal(command: str, timeout: int = 30) -> str:
    """
    Execute a shell command and return the combined stdout+stderr.

    Args:
        command: Shell command string to execute.
        timeout: Maximum execution time in seconds (default 30).

    Returns:
        A formatted string with exit code and output (truncated to 4000 chars).
    """
    # Strip surrounding whitespace
    command = command.strip()

    # Basic safety check for known destructive patterns
    lower_cmd = command.lower()
    warnings = []
    for prefix in _DANGEROUS_PREFIXES:
        if prefix in lower_cmd:
            warnings.append(
                f"⚠ WARNING: Command contains potentially destructive pattern: '{prefix.strip()}'"
            )

    warning_block = "\n".join(warnings) + "\n" if warnings else ""

    try:
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        output = result.stdout + result.stderr
    except subprocess.TimeoutExpired:
        return (
            f"{warning_block}"
            f"$ {command}\n"
            f"[Exit: TIMEOUT after {timeout}s]"
        )
    except Exception as e:
        return (
            f"{warning_block}"
            f"$ {command}\n"
            f"[Error: {e}]"
        )

    # Truncate very long outputs to keep context manageable
    MAX_CHARS = 4000
    if len(output) > MAX_CHARS:
        output = output[:MAX_CHARS] + f"\n... [truncated — {len(output)} total chars]"

    return (
        f"{warning_block}"
        f"$ {command}\n"
        f"{output.rstrip()}\n"
        f"[Exit: {result.returncode}]"
    )
