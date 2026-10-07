"""
AIHub Tool: Terminal access (v0.1.0).
Executes shell commands and returns the combined stdout+stderr output.
Includes a basic safety check for destructive commands.
"""
import subprocess
import sys

from .workdir import workdir

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

    # Windows: PowerShell (what people type there); elsewhere the POSIX shell.
    if sys.platform == "win32":
        argv = ["powershell", "-NoProfile", "-NonInteractive", "-Command", _powershell_script(command)]
        shell = False
    else:
        argv, shell = command, True
    try:
        result = subprocess.run(
            argv,
            shell=shell,
            cwd=workdir(),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
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


def _powershell_script(command: str) -> str:
    """Wrap a command so PowerShell's output reaches the model whole: UTF-8,
    no 120-column truncation of tables and paths ("C:\\Users\\…"), errors
    included, and a non-zero exit code when the command failed."""
    return (
        "$ErrorActionPreference = 'Continue'; "
        "[Console]::OutputEncoding = [Text.Encoding]::UTF8; "
        "$global:LASTEXITCODE = 0; $aihubErrors = $Error.Count; "
        "& {\n" + command + "\n} 2>&1 | Out-String -Stream -Width 4096; "
        "if ($LASTEXITCODE) { exit $LASTEXITCODE } "
        "elseif ($Error.Count -gt $aihubErrors) { exit 1 }"
    )
