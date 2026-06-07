#!/usr/bin/env bash
#
# AIHub-TUI installer.
#
# Run from a clone of the repo:
#     git clone https://github.com/marceljurgiel/AIhub-TUI.git && cd AIhub-TUI && ./install.sh
#
# Creates a local virtualenv (.venv) and installs the app + the `aihub`
# console command into it. Re-running is safe (idempotent).
#
# Options (env vars):
#   PYTHON=python3.12   Pick a specific interpreter (default: python3)
#   INSTALL_OLLAMA=1    Also install the Ollama runtime if it's missing
#
set -euo pipefail

cd "$(dirname "$0")"
REPO_DIR="$(pwd)"
PYBIN="${PYTHON:-python3}"

if ! command -v "$PYBIN" >/dev/null 2>&1; then
    echo "✗ '$PYBIN' not found. Install Python 3.9+ first (or set PYTHON=...)." >&2
    exit 1
fi

echo "→ AIHub-TUI install  ($REPO_DIR)"
echo "→ Using $("$PYBIN" --version)"

# 1. Virtualenv
if [ ! -d .venv ]; then
    echo "→ Creating virtualenv (.venv)…"
    "$PYBIN" -m venv .venv
fi
# shellcheck disable=SC1091
source .venv/bin/activate

# 2. Install the app
echo "→ Upgrading pip…"
python -m pip install --upgrade pip >/dev/null
echo "→ Installing AIHub-TUI (editable)…"
python -m pip install -e .

# 3. Optional: Ollama runtime (for local models)
if [ "${INSTALL_OLLAMA:-0}" = "1" ] && ! command -v ollama >/dev/null 2>&1; then
    echo "→ Installing Ollama…"
    curl -fsSL https://ollama.com/install.sh | sh || \
        echo "  (Ollama install failed — install it manually from https://ollama.com)"
fi

echo
echo "✓ Installed. Run it with:"
echo "    source $REPO_DIR/.venv/bin/activate && aihub"
echo
if ! command -v ollama >/dev/null 2>&1; then
    echo "Note: local models need the Ollama runtime — https://ollama.com/download"
    echo "      (or re-run with INSTALL_OLLAMA=1). Cloud API models work without it."
fi
