#!/usr/bin/env bash
# AIhub installer for Linux and macOS.
#
#   curl -fsSL https://raw.githubusercontent.com/marceljurgiel/AIhub-TUI/main/install.sh | bash
#
# Installs everything AIhub needs without root: uv (Python 3.12 + the engine),
# Bun (the terminal app) and a launcher at ~/.local/bin/aihub. Ollama is
# optional: install it locally, point AIhub at an Ollama server, or skip.
# Re-running it updates AIhub and keeps your settings (~/.aihub).
#
# Options (for unattended installs):
#   --yes                 don't ask; use the defaults
#   --ollama local|skip|<url>
#                         install Ollama here, skip it, or use the server at <url>
#   --model <name>|none   pull this model (default: one sized for this machine)
#   --knowledge           add knowledge bases: download the embedding model
#                         (embeddinggemma, ~620 MB) for searching your documents
#   --dir <path>          install directory (default: ~/.local/share/aihub)
#
# Environment: AIHUB_SOURCE  tarball URL or local .tar.gz to install from
#              AIHUB_REF     branch or tag on GitHub (default: main)
set -euo pipefail

REPO="marceljurgiel/AIhub-TUI"
REF="${AIHUB_REF:-main}"
SOURCE="${AIHUB_SOURCE:-https://github.com/$REPO/archive/refs/heads/$REF.tar.gz}"
INSTALLER_URL="https://raw.githubusercontent.com/$REPO/main/install.sh"
AIHUB_HOME="${AIHUB_HOME:-$HOME/.local/share/aihub}"
BIN_DIR="$HOME/.local/bin"
YES=0
OLLAMA_CHOICE=""
MODEL=""
KNOWLEDGE="${AIHUB_KNOWLEDGE:-}"

if [ -t 1 ]; then
  B=$'\033[1m'; DIM=$'\033[2m'; G=$'\033[32m'; Y=$'\033[33m'; R=$'\033[31m'; C=$'\033[36m'; N=$'\033[0m'
else
  B=""; DIM=""; G=""; Y=""; R=""; C=""; N=""
fi
step() { printf '\n%s==>%s %s%s%s\n' "$C" "$N" "$B" "$*" "$N"; }
ok()   { printf '  %s✓%s %s\n' "$G" "$N" "$*"; }
warn() { printf '  %s!%s %s\n' "$Y" "$N" "$*"; }
die()  { printf '\n%serror:%s %s\n' "$R" "$N" "$*" >&2; exit 1; }
have() { command -v "$1" >/dev/null 2>&1; }

# Prompts read the terminal, so they work under `curl … | bash` too.
ask() {  # ask "question" default → answer on stdout
  local q="$1" def="$2" ans=""
  if [ "$YES" = 1 ] || ! { : </dev/tty; } 2>/dev/null; then
    printf '%s\n' "$def"; return
  fi
  printf '  %s ' "$q" >/dev/tty
  read -r ans </dev/tty || ans=""
  printf '%s\n' "${ans:-$def}"
}

fetch() {  # fetch URL FILE
  if have curl; then curl -fsSL --retry 3 -o "$2" "$1"
  elif have wget; then wget -q -O "$2" "$1"
  else die "curl or wget is required"; fi
}

fetch_text() {  # fetch_text URL → body on stdout (short timeouts, for probes)
  if have curl; then curl -fsS --max-time 4 "$1" 2>/dev/null
  else wget -q -T 4 -O - "$1" 2>/dev/null; fi
}

parse_args() {
  while [ $# -gt 0 ]; do
    case "$1" in
      -y|--yes) YES=1 ;;
      --ollama) OLLAMA_CHOICE="${2:-}"; shift ;;
      --ollama=*) OLLAMA_CHOICE="${1#*=}" ;;
      --model) MODEL="${2:-}"; shift ;;
      --model=*) MODEL="${1#*=}" ;;
      --knowledge) KNOWLEDGE=1 ;;
      --dir) AIHUB_HOME="${2:-}"; shift ;;
      --dir=*) AIHUB_HOME="${1#*=}" ;;
      -h|--help) sed -n '2,20p' "$0" 2>/dev/null | sed 's/^# \{0,1\}//'; exit 0 ;;
      *) die "unknown option: $1 (try --help)" ;;
    esac
    shift
  done
}

# ── 1. AIhub itself ──────────────────────────────────────────────────────────
install_source() {
  step "Downloading AIhub"
  # Work next to the install, so every move below is a rename on one disk.
  mkdir -p "$(dirname "$AIHUB_HOME")"
  tmp="$(mktemp -d "$(dirname "$AIHUB_HOME")/.aihub-install.XXXXXX")"
  trap 'rm -rf "$tmp"' EXIT
  if [ -f "$SOURCE" ]; then cp "$SOURCE" "$tmp/aihub.tar.gz"; else fetch "$SOURCE" "$tmp/aihub.tar.gz"; fi
  mkdir -p "$tmp/src"
  tar -xzf "$tmp/aihub.tar.gz" -C "$tmp/src" --strip-components=1 || die "the download is not a valid archive: $SOURCE"
  [ -f "$tmp/src/pyproject.toml" ] && [ -d "$tmp/src/app" ] || die "the archive does not look like AIhub: $SOURCE"

  # Update: move the old install aside first (nothing changes if that fails),
  # keep the Python environment and the app's packages, swap the new one in.
  if [ -d "$AIHUB_HOME" ]; then
    mv "$AIHUB_HOME" "$tmp/old" || die "could not move the old install aside ($AIHUB_HOME) — nothing was changed"
    [ -d "$tmp/old/.venv" ] && mv "$tmp/old/.venv" "$tmp/src/.venv"
    [ -d "$tmp/old/app/node_modules" ] && mv "$tmp/old/app/node_modules" "$tmp/src/app/node_modules"
  fi
  mv "$tmp/src" "$AIHUB_HOME"
  ok "AIhub $(version_of) → $AIHUB_HOME"
}

version_of() {
  sed -n 's/^version[[:space:]]*=[[:space:]]*"\([^"]*\)".*/\1/p' "$AIHUB_HOME/pyproject.toml" | head -1
}

# ── 2. Python engine (uv brings its own Python, no root needed) ──────────────
install_engine() {
  step "Python engine"
  local uv=""
  for c in uv "$HOME/.local/bin/uv" "$HOME/.cargo/bin/uv"; do
    if have "$c" || [ -x "$c" ]; then uv="$(command -v "$c" || echo "$c")"; break; fi
  done
  if [ -z "$uv" ]; then
    fetch https://astral.sh/uv/install.sh "$AIHUB_HOME/.uv-install.sh"
    UV_NO_MODIFY_PATH=1 sh "$AIHUB_HOME/.uv-install.sh" -q >/dev/null || die "could not install uv"
    rm -f "$AIHUB_HOME/.uv-install.sh"
    uv="$HOME/.local/bin/uv"
    ok "uv installed"
  fi
  [ -x "$AIHUB_HOME/.venv/bin/python" ] || "$uv" venv -q --python 3.12 "$AIHUB_HOME/.venv" || die "could not create the Python environment"
  "$uv" pip install -q --python "$AIHUB_HOME/.venv/bin/python" -e "$AIHUB_HOME" || die "could not install the AIhub engine"
  ok "engine $("$AIHUB_HOME/.venv/bin/python" -c 'import aihub; print(aihub.__version__)') on Python $("$AIHUB_HOME/.venv/bin/python" -c 'import platform; print(platform.python_version())')"
}

# ── 3. Bun + the terminal app ────────────────────────────────────────────────
bun_target() {
  local os arch target
  os="$(uname -s)"; arch="$(uname -m)"
  case "$os" in Linux) os=linux ;; Darwin) os=darwin ;; *) die "unsupported system: $os" ;; esac
  case "$arch" in x86_64|amd64) arch=x64 ;; aarch64|arm64) arch=aarch64 ;; *) die "unsupported CPU: $arch" ;; esac
  target="$os-$arch"
  if [ "$os" = linux ]; then
    if ldd --version 2>&1 | grep -qi musl || [ -f /etc/alpine-release ]; then target="$target-musl"; fi
    if [ "$arch" = x64 ] && ! grep -qw avx2 /proc/cpuinfo 2>/dev/null; then target="$target-baseline"; fi
  elif [ "$arch" = x64 ] && [ "$(sysctl -n hw.optional.avx2_0 2>/dev/null || echo 1)" = 0 ]; then
    target="$target-baseline"
  fi
  printf '%s' "$target"
}

install_app() {
  step "Terminal app"
  BUN=""
  if have bun; then BUN="$(command -v bun)"; elif [ -x "$HOME/.bun/bin/bun" ]; then BUN="$HOME/.bun/bin/bun"; fi
  if [ -z "$BUN" ]; then
    # The official installer needs `unzip`; unpacking with our own Python doesn't.
    local target zip
    target="$(bun_target)"; zip="$AIHUB_HOME/.bun.zip"
    fetch "https://github.com/oven-sh/bun/releases/latest/download/bun-$target.zip" "$zip" || die "could not download Bun"
    mkdir -p "$HOME/.bun/bin"
    "$AIHUB_HOME/.venv/bin/python" - "$zip" "$target" "$HOME/.bun/bin/bun" <<'PY'
import shutil, sys, zipfile
with zipfile.ZipFile(sys.argv[1]) as z, z.open(f"bun-{sys.argv[2]}/bun") as src, open(sys.argv[3], "wb") as dst:
    shutil.copyfileobj(src, dst)
PY
    chmod +x "$HOME/.bun/bin/bun"; rm -f "$zip"
    BUN="$HOME/.bun/bin/bun"
    ok "Bun $("$BUN" --version) installed"
  fi
  (cd "$AIHUB_HOME/app" && "$BUN" install --production --frozen-lockfile >/dev/null 2>&1) \
    || (cd "$AIHUB_HOME/app" && "$BUN" install --production) || die "could not install the app's packages"
  ok "app ready (Bun $("$BUN" --version))"
}

# ── 4. Ollama ────────────────────────────────────────────────────────────────
OLLAMA_URL="http://localhost:11434"

ollama_up() { fetch_text "$1/api/version" | grep -q '"version"'; }

PY_HELPER() { "$AIHUB_HOME/.venv/bin/python" -m aihub.installer "$@"; }
set_server() { PY_HELPER server "$1" >/dev/null; }
normalize_url() { "$AIHUB_HOME/.venv/bin/python" -c 'import sys; from aihub.installer import normalize; print(normalize(sys.argv[1]))' "$1"; }

install_ollama_locally() {
  if [ "$(uname -s)" = Darwin ]; then
    if have brew; then brew install ollama && (brew services start ollama >/dev/null 2>&1 || true)
    else warn "install Ollama from https://ollama.com/download, then run aihub"; return 1; fi
  else
    have zstd || warn "Ollama's installer may need 'zstd' — install it with your package manager if the next step fails"
    fetch https://ollama.com/install.sh "$AIHUB_HOME/.ollama-install.sh"
    sh "$AIHUB_HOME/.ollama-install.sh" || { rm -f "$AIHUB_HOME/.ollama-install.sh"; warn "Ollama's installer failed"; return 1; }
    rm -f "$AIHUB_HOME/.ollama-install.sh"
  fi
  # Without systemd (containers, WSL) nothing starts the server for us.
  if ! ollama_up "$OLLAMA_URL" && have ollama; then
    (nohup ollama serve >/dev/null 2>&1 &)
    for _ in 1 2 3 4 5 6 7 8 9 10; do ollama_up "$OLLAMA_URL" && break; sleep 1; done
  fi
  ollama_up "$OLLAMA_URL"
}

setup_ollama() {
  step "Ollama"
  local choice="$OLLAMA_CHOICE" current
  current="$(PY_HELPER server 2>/dev/null || echo "$OLLAMA_URL")"
  if [ -z "$choice" ] && { ollama_up "$current" || PY_HELPER start >/dev/null 2>&1; }; then
    OLLAMA_URL="$current"; ok "Ollama is running at $OLLAMA_URL"; return 0
  fi
  if [ -z "$choice" ]; then
    printf '  AIhub runs models through Ollama, which is not reachable at %s.\n' "$current"
    printf '    %sL%s  install Ollama on this computer\n' "$B" "$N"
    printf '    %sS%s  use an Ollama server on your network (e.g. a PC with a GPU)\n' "$B" "$N"
    printf '    %sK%s  skip — set it up later in AIhub (Settings)\n' "$B" "$N"
    choice="$(ask "Choice [L/s/k]:" "$([ "$YES" = 1 ] && echo k || echo l)")"
  fi
  case "$choice" in
    l|L|local)
      install_ollama_locally && { set_server "$OLLAMA_URL"; ok "Ollama is running locally"; return 0; }
      warn "Ollama isn't running — start it later with 'ollama serve'"; return 1 ;;
    s|S|server)
      local url; url="$(ask "Server address (e.g. 192.0.2.10 or http://gpu-box.lan:11434):" "")"
      [ -n "$url" ] || { warn "no address given — skipped"; return 1; }
      choice="$url" ;;
    k|K|skip|none|"")
      warn "skipped — AIhub can still use Ollama Cloud or API models (Settings)"; return 1 ;;
  esac
  OLLAMA_URL="$(normalize_url "$choice")"
  if ollama_up "$OLLAMA_URL"; then
    set_server "$OLLAMA_URL"; ok "using the Ollama server at $OLLAMA_URL"
  else
    set_server "$OLLAMA_URL"
    warn "saved $OLLAMA_URL, but it does not answer right now (is Ollama listening on 0.0.0.0? OLLAMA_HOST=0.0.0.0)"
    return 1
  fi
}

ram_gb() {
  if [ -r /proc/meminfo ]; then awk '/MemTotal/ {printf "%d", $2/1024/1024 + 0.5}' /proc/meminfo
  else sysctl -n hw.memsize 2>/dev/null | awk '{printf "%d", $1/1073741824 + 0.5}'; fi
}

starter_model() {
  local ram; ram="$(ram_gb)"; ram="${ram:-8}"
  if [ "$ram" -lt 8 ]; then echo "llama3.2:1b"
  elif [ "$ram" -lt 16 ]; then echo "llama3.2:3b"
  else echo "qwen3:8b"; fi
}

setup_model() {
  [ "$MODEL" = none ] && return 0
  local count model
  count="$(PY_HELPER models "$OLLAMA_URL" 2>/dev/null || echo 0)"
  if [ -z "$MODEL" ] && [ "${count:-0}" -gt 0 ]; then
    ok "$count model(s) already available"; return 0
  fi
  model="${MODEL:-$(starter_model)}"
  if [ -z "$MODEL" ]; then
    local ans; ans="$(ask "Download a starter model, $model ($(ram_gb) GB RAM here)? [Y/n/other name]:" "$([ "$YES" = 1 ] && echo n || echo y)")"
    case "$ans" in y|Y|yes) ;; n|N|no) printf '  pick models later in AIhub → Models\n'; return 0 ;; *) model="$ans" ;; esac
  fi
  step "Downloading $model"
  if have ollama && [ "$OLLAMA_URL" = "http://localhost:11434" ]; then
    ollama pull "$model" || warn "could not download $model"
  else
    PY_HELPER pull "$OLLAMA_URL" "$model" || warn "could not download $model"
  fi
}

# Knowledge bases need an embedding model on the Ollama server.
setup_knowledge() {
  local model="embeddinggemma" ans="$KNOWLEDGE"
  PY_HELPER has "$OLLAMA_URL" "$model" && { ok "knowledge bases ready ($model)"; return 0; }
  if [ -z "$ans" ]; then
    ans="$(ask "Add knowledge bases — search your own documents? Downloads $model (~620 MB) [y/N]:" n)"
  fi
  case "$ans" in y|Y|yes|1|true) ;; *) return 0 ;; esac
  step "Knowledge bases ($model)"
  PY_HELPER pull "$OLLAMA_URL" "$model" || warn "could not download $model — AIhub offers it again in Knowledge (F6)"
}

# ── 5. Launcher ──────────────────────────────────────────────────────────────
install_launcher() {
  step "Launcher"
  mkdir -p "$BIN_DIR"
  # Replace, never write through: an older aihub here may be a symlink into
  # someone's checkout, and writing to it would overwrite that file.
  rm -f "$BIN_DIR/aihub"
  cat >"$BIN_DIR/aihub" <<EOF
#!/bin/sh
# AIhub launcher (written by install.sh). Re-run the installer to update.
AIHUB_HOME="$AIHUB_HOME"
BUN="$BUN"
case "\${1:-}" in
  update)  shift; curl -fsSL "$INSTALLER_URL" | bash -s -- --dir "\$AIHUB_HOME" "\$@"; exit \$? ;;
  version|--version|-v)
           sed -n 's/^version *= *"\\(.*\\)"/aihub \\1/p' "\$AIHUB_HOME/pyproject.toml"; exit 0 ;;
  cli)     shift; exec "\$AIHUB_HOME/.venv/bin/aihub-cli" "\$@" ;;
  uninstall)
           printf 'Remove AIhub from %s? Your chats and settings in ~/.aihub stay. [y/N] ' "\$AIHUB_HOME"
           read -r a; [ "\$a" = y ] || exit 1
           rm -rf "\$AIHUB_HOME" "\$0"; echo "AIhub removed."; exit 0 ;;
  help|--help|-h)
           echo "aihub            start AIhub"
           echo "aihub update     update to the latest version"
           echo "aihub cli ...    command-line tools (models, hardware)"
           echo "aihub version    show the installed version"
           echo "aihub uninstall  remove AIhub (keeps ~/.aihub)"; exit 0 ;;
esac
export AIHUB_CORE_DIR="\$AIHUB_HOME"
# The app works in the folder you start it from; Bun itself runs from app/
# so it picks up the app's tsconfig (JSX setup).
export AIHUB_WORKDIR="\${AIHUB_WORKDIR:-\$PWD}"
cd "\$AIHUB_HOME/app" || exit 1
exec "\$BUN" run src/index.tsx "\$@"
EOF
  chmod +x "$BIN_DIR/aihub"
  ok "$BIN_DIR/aihub"

  case ":$PATH:" in
    *":$BIN_DIR:"*) ;;
    *)
      local line="export PATH=\"\$HOME/.local/bin:\$PATH\"" rc added=""
      for rc in "$HOME/.bashrc" "$HOME/.zshrc" "$HOME/.profile"; do
        [ -f "$rc" ] || continue
        grep -qs '.local/bin' "$rc" || { printf '\n%s\n' "$line" >>"$rc"; added="$added $rc"; }
      done
      [ -n "$added" ] && ok "added ~/.local/bin to PATH in$added"
      PATH_HINT=1 ;;
  esac
}

main() {
  parse_args "$@"
  have tar || die "tar is required"
  printf '%sAIhub installer%s %s— local AI in your terminal%s\n' "$B" "$N" "$DIM" "$N"
  install_source
  install_engine
  install_app
  PATH_HINT=0
  if setup_ollama; then setup_model; setup_knowledge; fi
  install_launcher

  printf '\n%s✓ AIhub %s is installed.%s\n' "$G$B" "$(version_of)" "$N"
  if [ "$PATH_HINT" = 1 ]; then
    printf '  Open a new terminal (or run: %sexport PATH="$HOME/.local/bin:$PATH"%s), then start it with %saihub%s\n' "$B" "$N" "$B" "$N"
  else
    printf '  Start it with: %saihub%s\n' "$B" "$N"
  fi
  printf '  %sUpdate later with "aihub update". Free cloud models: run "ollama signin" and pick a :cloud model.%s\n' "$DIM" "$N"
}

main "$@"
