#!/bin/bash
# setup_pi.sh — Raspberry Pi environment setup
# Usage:   ./setup_pi.sh
# Idempotent: safe to re-run; skips steps that are already done.

set -euo pipefail

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null 2>&1 && pwd )"

echo "============================================="
echo "   AMBIENT AI HUB - RASPBERRY PI SETUP       "
echo "============================================="

# ── Prerequisite check ──────────────────────────────────────────────────────
if ! command -v python3 &>/dev/null; then
    echo "[ERROR] python3 not found. Please install it first." >&2
    exit 1
fi

PYTHON_MINOR=$(python3 -c "import sys; print(sys.version_info.minor)")
if [ "$PYTHON_MINOR" -lt 9 ]; then
    echo "[ERROR] Python 3.9+ required. Found 3.$PYTHON_MINOR" >&2
    exit 1
fi

# ── [1/5] System packages ───────────────────────────────────────────────────
echo "[1/5] Installing system dependencies..."
sudo apt-get update -qq
sudo apt-get install -y --no-install-recommends \
    python3-opencv \
    espeak \
    portaudio19-dev \
    libasound2-dev \
    libatlas-base-dev \
    git \
    curl

# ── [2/5] Python virtual environment ────────────────────────────────────────
echo "[2/5] Setting up Python virtual environment..."
VENV_DIR="$SCRIPT_DIR/.venv"
if [ ! -d "$VENV_DIR" ]; then
    python3 -m venv "$VENV_DIR"
    echo "Virtual environment created at $VENV_DIR"
else
    echo "Virtual environment already exists — skipping creation."
fi
# shellcheck source=/dev/null
source "$VENV_DIR/bin/activate"
pip install --upgrade pip --quiet

# ── [3/5] Python packages ───────────────────────────────────────────────────
echo "[3/5] Installing Python dependencies..."
pip install -r "$SCRIPT_DIR/requirements.txt" --quiet

# ── [4/5] Vosk model ────────────────────────────────────────────────────────
echo "[4/5] Checking Vosk speech model..."
VOSK_MODEL_DIR="$HOME/.cache/vosk/vosk-model-small-en-us-0.15"
if [ ! -d "$VOSK_MODEL_DIR" ]; then
    echo "Downloading Vosk small English model (~40 MB)..."
    python3 -c "import vosk; vosk.Model(model_name='vosk-model-small-en-us-0.15')"
    echo "Vosk model downloaded."
else
    echo "Vosk model already present — skipping."
fi

# ── [5/5] Ollama ─────────────────────────────────────────────────────────────
echo "[5/5] Checking Ollama..."
if ! command -v ollama &>/dev/null; then
    echo "Installing Ollama..."
    curl -fsSL https://ollama.com/install.sh | sh
fi

echo "Checking llama3.2:1b model..."
if ! ollama list | grep -q "llama3.2:1b"; then
    echo "Pulling llama3.2:1b model (this may take several minutes)..."
    ollama pull llama3.2:1b
else
    echo "llama3.2:1b model already present — skipping."
fi

# ── Pre-flight checklist ─────────────────────────────────────────────────────
echo ""
echo "============================================="
echo " PRE-FLIGHT CHECKS                          "
echo "============================================="
WARNINGS=0

if grep -q 'CHANGE_ME_BEFORE_DEPLOY' "$SCRIPT_DIR/config.yaml" 2>/dev/null; then
    echo "  [WARN] api_secret_token is still the placeholder!"
    echo "         Run: python3 -c \"import secrets; print(secrets.token_hex(32))\""
    echo "         Then paste the result into config.yaml under api_secret_token."
    WARNINGS=$((WARNINGS+1))
else
    echo "  [OK]  api_secret_token is set."
fi

if [ ! -f "$SCRIPT_DIR/yolov8n-pose.pt" ]; then
    echo "  [WARN] yolov8n-pose.pt is MISSING — vision engine will crash!"
    echo "         Copy it from your PC alongside the Python files."
    WARNINGS=$((WARNINGS+1))
else
    echo "  [OK]  yolov8n-pose.pt present."
fi

if [ ! -f "$SCRIPT_DIR/owner_face_model.yml" ]; then
    echo "  [WARN] owner_face_model.yml not found — face recognition disabled."
    echo "         Run: source .venv/bin/activate && python3 enroll_owner.py"
    WARNINGS=$((WARNINGS+1))
else
    echo "  [OK]  owner_face_model.yml present."
fi

if [ "$WARNINGS" -eq 0 ]; then
    echo "  [OK]  All checks passed. Ready to install services."
fi

echo "============================================="
echo " SETUP COMPLETE!                             "
echo "                                             "
echo " IMPORTANT — do these before installing:     "
echo "   1. Set api_secret_token in config.yaml    "
echo "      python3 -c 'import secrets;print(secrets.token_hex(32))'"
echo "   2. Enroll face: python3 enroll_owner.py   "
echo "                                             "
echo " Then install auto-start services:           "
echo "   sudo ./install_services.sh               "
echo "============================================="
