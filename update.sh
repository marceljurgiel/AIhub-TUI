#!/usr/bin/env bash
#
# AIHub-TUI updater — force-syncs this checkout to the latest pushed version.
#
#   ./update.sh
#
# Unlike `git pull`, this never gets blocked by local edits or a diverged
# branch: it fetches origin and hard-resets to origin/main, then reinstalls so
# any dependency changes are picked up. Run it any time new changes are pushed.
#
# ⚠ This DISCARDS local changes in this checkout (intended for a deploy/test box).
#
set -euo pipefail
cd "$(dirname "$0")"

BRANCH="${BRANCH:-main}"

echo "→ Fetching latest from origin…"
git fetch origin "$BRANCH"

echo "→ Hard-resetting to origin/$BRANCH (discards local edits)…"
git reset --hard "origin/$BRANCH"
git clean -fd -e .venv >/dev/null 2>&1 || true   # drop stray untracked files, keep the venv

echo "→ Now on: $(git log --oneline -1)"

if [ -d .venv ]; then
    # shellcheck disable=SC1091
    source .venv/bin/activate
    echo "→ Reinstalling (picks up any dependency changes)…"
    python -m pip install -e . >/dev/null
    echo
    echo "✓ Updated. Run it with:  source $(pwd)/.venv/bin/activate && aihub"
else
    echo
    echo "✓ Code updated. No .venv found — run ./install.sh once to set it up."
fi
