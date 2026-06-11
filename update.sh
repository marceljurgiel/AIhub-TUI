#!/usr/bin/env bash
#
# AIHub-TUI updater — force-syncs this checkout to the latest pushed version and
# guarantees an EDITABLE install so the `aihub` command actually reflects the
# pulled code (the #1 "I updated but nothing changed" cause is a frozen,
# non-editable install).
#
#   ./update.sh
#
# ⚠ DISCARDS local changes in this checkout (intended for a deploy/test box).
#
set -euo pipefail
cd "$(dirname "$0")"

BRANCH="${BRANCH:-main}"
PYBIN="${PYTHON:-python3}"

echo "→ Fetching latest from origin…"
git fetch origin "$BRANCH"
echo "→ Hard-resetting to origin/$BRANCH…"
git reset --hard "origin/$BRANCH"
git clean -fd -e .venv >/dev/null 2>&1 || true
echo "→ Now on: $(git log --oneline -1)"

# Ensure a venv exists, then (re)install EDITABLE so source changes take effect.
[ -d .venv ] || { echo "→ Creating virtualenv (.venv)…"; "$PYBIN" -m venv .venv; }
# shellcheck disable=SC1091
source .venv/bin/activate
echo "→ Reinstalling (editable)…"
python -m pip install -e . >/dev/null

# (Re)link `aihub` onto PATH so the command works in any shell and points at
# this editable install — overriding any older frozen copy.
AIHUB_BIN="$(pwd)/.venv/bin/aihub"
for d in /usr/local/bin "$HOME/.local/bin"; do
    if [ -d "$d" ] && { [ -w "$d" ] || [ "$(id -u)" -eq 0 ]; }; then
        ln -sf "$AIHUB_BIN" "$d/aihub" 2>/dev/null && \
            echo "→ Linked: $d/aihub" && break
    fi
done

VER="$(python -c 'import aihub; print(aihub.__version__)' 2>/dev/null || echo '?')"
echo
echo "✓ Updated to $(git log --oneline -1 | cut -c1-7) (AIHub v$VER). Run:  aihub"
echo "  (restart aihub if it's already open: Ctrl+Q, then 'aihub')"
