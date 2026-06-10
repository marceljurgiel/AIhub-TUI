#!/usr/bin/env bash
#
# AIHub-TUI installer.
#
# Run from a clone of the repo:
#     git clone https://github.com/marceljurgiel/AIhub-TUI.git && cd AIhub-TUI && ./install.sh
#
# Installs any missing system packages (git, python3, venv, pip), creates a
# local virtualenv (.venv), and installs the app + the `aihub` console command.
# Re-running is safe (idempotent). Works on Debian/Ubuntu, Fedora/RHEL, Arch,
# and openSUSE. Uses sudo automatically when not run as root.
#
# Options (env vars):
#   PYTHON=python3.12   Pick a specific interpreter (default: python3)
#   INSTALL_OLLAMA=1    Also install the Ollama runtime if it's missing
#   FORCE_DEPS=1        Re-run the system-package step even if tools look present
#
set -euo pipefail

cd "$(dirname "$0")"
REPO_DIR="$(pwd)"

# Use sudo only when needed (no-op as root).
SUDO=""
if [ "$(id -u)" -ne 0 ]; then
    command -v sudo >/dev/null 2>&1 && SUDO="sudo"
fi

install_system_deps() {
    local id="unknown"
    [ -r /etc/os-release ] && . /etc/os-release && id="${ID:-unknown}"
    echo "→ Installing system dependencies (git, python3, venv, pip)…  [distro: $id]"
    case "$id" in
        ubuntu|debian|linuxmint|pop|raspbian|kali)
            export DEBIAN_FRONTEND=noninteractive
            $SUDO apt-get update -y
            $SUDO apt-get install -y git curl python3 python3-venv python3-pip ;;
        fedora|rhel|centos|rocky|almalinux|ol)
            $SUDO dnf install -y git curl python3 python3-pip ;;
        arch|manjaro|endeavouros|cachyos)
            $SUDO pacman -Sy --noconfirm git curl python python-pip ;;
        opensuse*|sles|sled)
            $SUDO zypper install -y git curl python3 python3-pip python3-virtualenv ;;
        *)
            echo "  ⚠ Unknown distro '$id'. Make sure git, python3, python3-venv and pip"
            echo "    are installed, then re-run this script." ;;
    esac
}

# Install system deps if any are missing (or FORCE_DEPS=1).
need_deps=0
command -v git     >/dev/null 2>&1 || need_deps=1
command -v python3 >/dev/null 2>&1 || need_deps=1
python3 -c "import venv"  >/dev/null 2>&1 || need_deps=1
python3 -m pip --version  >/dev/null 2>&1 || need_deps=1
if [ "$need_deps" -eq 1 ] || [ "${FORCE_DEPS:-0}" = "1" ]; then
    install_system_deps
else
    echo "→ System dependencies already present."
fi

PYBIN="${PYTHON:-python3}"
if ! command -v "$PYBIN" >/dev/null 2>&1; then
    echo "✗ '$PYBIN' still not found after install. Install Python 3.9+ manually." >&2
    exit 1
fi
echo "→ Using $("$PYBIN" --version)"

# Virtualenv + app install.
[ -d .venv ] || { echo "→ Creating virtualenv (.venv)…"; "$PYBIN" -m venv .venv; }
# shellcheck disable=SC1091
source .venv/bin/activate
echo "→ Upgrading pip…"
python -m pip install --upgrade pip >/dev/null
echo "→ Installing AIHub-TUI…"
python -m pip install -e .

# Optional: Ollama runtime (for local models).
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
