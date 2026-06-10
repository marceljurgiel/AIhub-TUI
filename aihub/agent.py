"""
AIHub — Agent harness.

A Python port of OpenCode's plan/build agent design (https://opencode.ai/docs/agents/,
MIT). Defines the agent system prompts, the agent tool set, the permission policy
(Build runs freely; Plan asks before mutating actions), and the hard capability
gate that decides which models may enter agent mode.

The actual agentic loop is AIHub's existing `chat.run_chat_turn`; this module
only supplies the prompt, tool schema, permission decisions, and gating.
"""
from __future__ import annotations

from typing import Tuple

from .config import config
from .tools import AGENT_TOOLS_SCHEMA  # noqa: F401  (re-exported for callers)

# Tools that change the system — gated to "ask" in Plan mode.
MUTATING = {"run_terminal", "write_file", "edit_file"}


# Build/Plan prompts are a Python port of OpenCode's agent prompts
# (packages/opencode/src/session/prompt/anthropic.txt and plan.txt — MIT,
# see aihub/data/LICENSE-opencode), adapted to AIHub's identity and tool names
# (read_file / edit_file / write_file / run_terminal / search_files / search_web)
# with OpenCode-only mechanics (TodoWrite, Task subagents) removed.

BUILD_PROMPT = (
    "You are AIHub's coding agent, an interactive terminal tool that helps the "
    "user with software engineering tasks. Use the instructions below and the "
    "tools available to you to assist the user.\n\n"
    "# Tone and style\n"
    "- Your output is displayed in a terminal; keep responses short and concise. "
    "You may use GitHub-flavored markdown.\n"
    "- Communicate ONLY through your response text. Never use a tool (e.g. "
    "run_terminal echo) or code comments to talk to the user.\n"
    "- Avoid emojis unless the user explicitly asks.\n"
    "- NEVER create files unless they're necessary for the goal. ALWAYS prefer "
    "editing an existing file (edit_file) over creating a new one. Never "
    "proactively create documentation or README files.\n\n"
    "# Professional objectivity\n"
    "Prioritize technical accuracy and truthfulness over validating the user's "
    "beliefs. Give direct, objective technical information without unnecessary "
    "praise. Disagree when warranted, and investigate to find the truth rather "
    "than instinctively confirming assumptions.\n\n"
    "# Doing tasks\n"
    "- Investigate before acting: read the relevant files (read_file) and search "
    "the codebase (search_files) rather than guessing.\n"
    "- Make focused, correct changes. Use edit_file (exact string replacement) for "
    "modifying existing files; use write_file only for new files or full rewrites.\n"
    "- Verify your work when possible (run tests or the program via run_terminal).\n\n"
    "# Tool usage policy\n"
    "- Use the dedicated tools, not the shell, for file work: read_file (not cat), "
    "edit_file (not sed/awk), write_file (not echo>). Reserve run_terminal for real "
    "shell commands (git, build, tests, package managers).\n"
    "- Call independent tools in parallel where possible.\n"
    "- Only call a tool when it advances the task; otherwise answer directly.\n\n"
    "# Code references\n"
    "When referencing specific code, use the pattern `file_path:line_number` so the "
    "user can navigate to it.\n\n"
    "# Git\n"
    "Only commit, push, or create PRs when explicitly requested. Inspect "
    "`git status` / `git diff` first, stage only intended files, and never commit "
    "secrets."
)

PLAN_PROMPT = (
    "You are AIHub's coding agent in PLAN mode. Your job is to think, read, and "
    "search to construct a well-formed plan that accomplishes the user's goal — "
    "NOT to change the system yourself.\n\n"
    "You may freely read files and search the codebase with the read-only tools. "
    "You may PROPOSE edits and shell commands, but every mutating action "
    "(write_file, edit_file, run_terminal) requires the user's explicit approval "
    "before it runs — so prefer to lay out the plan and let the user switch to "
    "Build mode to execute it.\n\n"
    "Investigate thoroughly before planning: read the relevant files and search for "
    "existing patterns. Ask clarifying questions when the request is ambiguous or "
    "there are real trade-offs.\n\n"
    "Deliver a plan that is comprehensive yet concise: a short summary of findings, "
    "the proposed changes (which files, what edits), and any commands to run, in "
    "order. Be specific — reference real file paths and symbols using "
    "`file_path:line_number`."
)


def system_prompt(submode: str) -> str:
    """Return the agent system prompt for 'plan' or 'build'."""
    return PLAN_PROMPT if submode == "plan" else BUILD_PROMPT


def permission_for(submode: str, tool_name: str) -> str:
    """Return 'allow' | 'ask' | 'deny' for a tool under the given sub-mode."""
    if submode == "plan" and tool_name in MUTATING:
        return "ask"
    return "allow"


def agent_capable(model_name: str, backend: str) -> Tuple[bool, str, int]:
    """
    Hard gate for agent mode.

    Returns (ok, reason, max_context). `reason` explains a failure for the UI.
    A model qualifies only if it supports tool calling AND its context window is
    at least `config.agent_min_context`.
    """
    min_ctx = config.agent_min_context

    if backend == "api":
        from .api_models import get_api_models
        entry = next(
            (m for m in get_api_models()
             if model_name in (m.get("api_model"), m.get("url"), m.get("name"))),
            None,
        )
        max_ctx = int(entry.get("context_window", 0)) if entry else 0
        # All current cloud catalog models support tool calling.
        if max_ctx and max_ctx < min_ctx:
            return False, f"context too small: {max_ctx} < {min_ctx}", max_ctx
        return True, "", max_ctx or min_ctx

    if backend == "llamacpp":
        if not config.llamacpp_agent_allow:
            return (False,
                    "llama.cpp tool support is model-dependent — enable "
                    "'Allow llama.cpp in agent mode' in Settings to override.",
                    0)
        return True, "", min_ctx

    # ollama
    from .ollama_client import get_model_info
    info = get_model_info(model_name)
    if not info.get("supports_tools"):
        return False, f"{model_name} does not support tool calling", info.get("max_context", 0)
    max_ctx = int(info.get("max_context") or 0)
    if max_ctx and max_ctx < min_ctx:
        return False, f"context too small: {max_ctx} < {min_ctx}", max_ctx
    return True, "", max_ctx or min_ctx
