#!/bin/bash
# install_services.sh — Systemd service installer for Ambient AI Hub
# Usage:   sudo ./install_services.sh [--uninstall]
# Idempotent: safe to re-run.

set -euo pipefail

# ── Root check ───────────────────────────────────────────────────────────────
if [ "$EUID" -ne 0 ]; then
    echo "[ERROR] Run with sudo: sudo ./install_services.sh" >&2
    exit 1
fi

DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null 2>&1 && pwd )"
USER_NAME=$(logname)
VENV_PYTHON="$DIR/.venv/bin/python3"
VENV_STREAMLIT="$DIR/.venv/bin/streamlit"

# Fallback to system python if venv not present
if [ ! -f "$VENV_PYTHON" ]; then
    VENV_PYTHON="/usr/bin/python3"
    VENV_STREAMLIT="/usr/local/bin/streamlit"
    echo "[WARN] Virtual environment not found — using system Python."
fi

# ── Prerequisite check ───────────────────────────────────────────────────────
if [ ! -f "$DIR/voice_assistant.py" ]; then
    echo "[ERROR] voice_assistant.py not found in $DIR" >&2
    exit 1
fi
if [ ! -f "$DIR/yolo_tracker.py" ]; then
    echo "[ERROR] yolo_tracker.py not found in $DIR" >&2
    exit 1
fi
if [ ! -f "$DIR/dashboard.py" ]; then
    echo "[ERROR] dashboard.py not found in $DIR" >&2
    exit 1
fi

# ── Uninstall mode ───────────────────────────────────────────────────────────
if [[ "${1:-}" == "--uninstall" ]]; then
    echo "Uninstalling Ambient AI Hub services..."
    systemctl stop  ambient-brain ambient-eyes ambient-dashboard 2>/dev/null || true
    systemctl disable ambient-brain ambient-eyes ambient-dashboard 2>/dev/null || true
    rm -f /etc/systemd/system/ambient-brain.service \
          /etc/systemd/system/ambient-eyes.service \
          /etc/systemd/system/ambient-dashboard.service
    systemctl daemon-reload
    echo "Services removed."
    exit 0
fi

echo "============================================="
echo "   AMBIENT AI HUB - AUTO-START SETUP         "
echo "============================================="
echo "Installing services in: $DIR"
echo "Running as user:        $USER_NAME"

# ── [1/3] Brain service ──────────────────────────────────────────────────────
cat > /etc/systemd/system/ambient-brain.service <<EOF
[Unit]
Description=Ambient AI Brain (Voice & API)
After=network.target sound.target ollama.service
Requires=ollama.service
# Disable start limits so it keeps trying indefinitely if USB mic is slow
StartLimitIntervalSec=0

[Service]
Type=simple
User=$USER_NAME
WorkingDirectory=$DIR
ExecStart=$VENV_PYTHON $DIR/voice_assistant.py
Environment="HEADLESS=true"
Restart=always
RestartSec=10
MemoryMax=512M
CPUQuota=80%
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

# ── [2/3] Eyes service ───────────────────────────────────────────────────────
cat > /etc/systemd/system/ambient-eyes.service <<EOF
[Unit]
Description=Ambient AI Eyes (Vision & YOLO)
After=network.target ambient-brain.service
Wants=ambient-brain.service
# Disable start limits so it keeps trying indefinitely if USB camera is slow
StartLimitIntervalSec=0

[Service]
Type=simple
User=$USER_NAME
WorkingDirectory=$DIR
ExecStart=$VENV_PYTHON $DIR/yolo_tracker.py
Environment="HEADLESS=true"
Restart=always
RestartSec=10
MemoryMax=512M
CPUQuota=90%
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

# ── [3/3] Dashboard service ──────────────────────────────────────────────────
cat > /etc/systemd/system/ambient-dashboard.service <<EOF
[Unit]
Description=Ambient AI Dashboard (Streamlit)
After=network.target ambient-brain.service
Wants=ambient-brain.service
# Disable start limits so it keeps trying indefinitely
StartLimitIntervalSec=0

[Service]
Type=simple
User=$USER_NAME
WorkingDirectory=$DIR
ExecStart=$VENV_STREAMLIT run $DIR/dashboard.py \
    --server.port 8501 \
    --server.address 0.0.0.0 \
    --server.headless true \
    --server.fileWatcherType none
Environment="HEADLESS=true"
Restart=always
RestartSec=10
MemoryMax=256M
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

# ── Reload and enable ────────────────────────────────────────────────────────
echo "Reloading systemd daemon..."
systemctl daemon-reload

echo "Enabling services for auto-start on boot..."
systemctl enable ambient-brain.service ambient-eyes.service ambient-dashboard.service

echo "============================================="
echo " SUCCESS!                                    "
echo "                                             "
echo " Services will start on next boot.           "
echo " To start NOW without rebooting:             "
echo "   sudo systemctl start ambient-brain ambient-eyes ambient-dashboard"
echo "                                             "
echo " Dashboard: http://<PI_IP_ADDRESS>:8501      "
echo " Brain API: http://127.0.0.1:5000/health     "
echo "                                             "
echo " To uninstall: sudo ./install_services.sh --uninstall"
echo "============================================="
