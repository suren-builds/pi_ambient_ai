#!/bin/bash
echo "============================================="
echo "   AMBIENT AI HUB - RASPBERRY PI SETUP       "
echo "============================================="

echo "[1/4] Updating package lists..."
sudo apt update

echo "[2/4] Installing system dependencies (Audio & Vision)..."
# OpenCV system libs, espeak for TTS, portaudio for microphone
sudo apt install -y python3-opencv espeak portaudio19-dev libasound2-dev

echo "[3/4] Installing Python dependencies..."
# We use --break-system-packages if running on modern Debian (Bookworm+)
# Alternatively, setting up a venv is recommended.
python3 -m pip install -r requirements.txt --break-system-packages || python3 -m pip install -r requirements.txt

echo "[4/4] Installing Ollama (for local LLM)..."
if ! command -v ollama &> /dev/null
then
    curl -fsSL https://ollama.com/install.sh | sh
    echo "Pulling llama3.2:1b model... (This might take a while)"
    ollama run llama3.2:1b "Hello"
else
    echo "Ollama is already installed."
fi

echo "============================================="
echo " SETUP COMPLETE! "
echo " Run the components in separate terminals: "
echo " 1. python3 voice_assistant.py"
echo " 2. python3 yolo_tracker.py"
echo " 3. streamlit run dashboard.py"
echo "============================================="
