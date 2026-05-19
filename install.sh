#!/usr/bin/env bash

set -e

echo "====================================================="
echo "        Instalacja AIHub - Pierwsze kroki            "
echo "====================================================="

if [ -f /etc/os-release ]; then
    . /etc/os-release
    OS=$ID
else
    echo "Nie można wykryć systemu operacyjnego. Instalka może zawieść."
    OS="unknown"
fi

echo "[1/4] Instalacja zależności systemowych git, curl, python3, pip..."
if [[ "$OS" == "ubuntu" || "$OS" == "debian" ]]; then
    sudo apt-get update
    sudo apt-get install -y git curl python3 python3-pip python3-venv
elif [[ "$OS" == "fedora" || "$OS" == "rhel" ]]; then
    sudo dnf install -y git curl python3 python3-pip
elif [[ "$OS" == "arch" || "$OS" == "manjaro" ]]; then
    sudo pacman -Sy --noconfirm git curl python python-pip pciutils
else
    echo "Nieznany system: $OS. Upewnij się, że zależne programy są zainstalowane."
fi

echo "[2/4] Instalowanie Ollama..."
if ! command -v ollama &> /dev/null; then
    curl -fsSL https://ollama.com/install.sh | sh
    echo "Uruchamiam usługę Ollama w tle (lub za pomocą systemd)..."
    sudo systemctl enable ollama || true
    sudo systemctl start ollama || true
    sleep 3
else
    echo "Ollama jest już zainstalowana."
fi

echo "[3/4] Pobieranie domyślnego modelu Ollamy (qwen:0.5b jako szybki start)..."
if systemctl is-active --quiet ollama; then
    ollama pull qwen:0.5b || echo "Nie udało się pobrać modelu startowego, pomijam."
else
    echo "Ollama daemon nie działa w tym momencie. Pomijam pobieranie."
fi

echo "[4/4] Instalowanie aplikacji AIHub..."
APP_DIR="$HOME/.aihub/repo"

if [ ! -d "$APP_DIR" ]; then
    echo "Tworzenie środowiska aplikacji w $APP_DIR..."
    mkdir -p "$APP_DIR"
    
    if [ -d "$PWD/aihub" ] && [ -f "$PWD/requirements.txt" ]; then
        cp -r "$PWD"/* "$APP_DIR"
    elif [ -d "/home/marcel-desktop/.gemini/antigravity/scratch/aihub" ]; then
        cp -r /home/marcel-desktop/.gemini/antigravity/scratch/aihub/* "$APP_DIR"
    else
        echo "Brak odpowiednich plików instalacyjnych. Klonowanie..."
        # git clone https://github.com/example/aihub.git "$APP_DIR"
    fi
fi

cd "$APP_DIR"

if [ -f "pyproject.toml" ]; then
    echo "Instalacja za pomocą pip..."
    python3 -m pip install -e . --break-system-packages 2>/dev/null || python3 -m pip install -e . || echo "Spróbuj zainstalować w venv lub za pomocą --user."
else
    echo "Brak pliku pyproject.toml, instalacja przerwana."
    exit 1
fi

mkdir -p "$HOME/.aihub"

# Skopiuj domyślny konfigurator, jesli go nie ma
if [ ! -f "$HOME/.aihub/config.yaml" ]; then
    cat <<EOF > "$HOME/.aihub/config.yaml"
# AIHub Konfiguracja
models_registry_path: "$APP_DIR/models_registry.json"
default_chat_model: "qwen:0.5b"
ollama_api_url: "http://localhost:11434"
EOF
fi

echo "====================================================="
echo "  Instalacja zakończona sukcesem! Wpisz 'aihub'      "
echo "  w terminalu, aby rozpocząć pracę.                  "
echo "====================================================="
