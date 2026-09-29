#!/bin/bash
echo "============================================="
echo "   AMBIENT AI HUB - AUTO-START SETUP         "
echo "============================================="

if [ "$EUID" -ne 0 ]
  then echo "Please run this script with sudo: sudo ./install_services.sh"
  exit
fi

# Get the absolute path to this directory
DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null 2>&1 && pwd )"
USER_NAME=$(logname)

echo "Setting up services to run from directory: $DIR"
echo "Services will run as user: $USER_NAME"

# 1. Create Brain Service (Voice Assistant & API)
cat <<EOF > /etc/systemd/system/ambient-brain.service
[Unit]
Description=Ambient AI Brain (Voice & API)
After=network.target sound.target
Wants=ollama.service

[Service]
Type=simple
User=$USER_NAME
WorkingDirectory=$DIR
ExecStart=/usr/bin/python3 $DIR/voice_assistant.py
Environment="HEADLESS=true"
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

# 2. Create Eyes Service (YOLO Tracker)
cat <<EOF > /etc/systemd/system/ambient-eyes.service
[Unit]
Description=Ambient AI Eyes (Vision & YOLO)
After=network.target ambient-brain.service

[Service]
Type=simple
User=$USER_NAME
WorkingDirectory=$DIR
ExecStart=/usr/bin/python3 $DIR/yolo_tracker.py
Environment="HEADLESS=true"
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

# 3. Create Dashboard Service (Streamlit UI)
cat <<EOF > /etc/systemd/system/ambient-dashboard.service
[Unit]
Description=Ambient AI Dashboard
After=network.target ambient-brain.service

[Service]
Type=simple
User=$USER_NAME
WorkingDirectory=$DIR
ExecStart=/usr/local/bin/streamlit run $DIR/dashboard.py --server.port 8501 --server.address 0.0.0.0 --server.headless true
Environment="HEADLESS=true"
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

echo "Reloading systemd daemon..."
systemctl daemon-reload

echo "Enabling services to start on boot..."
systemctl enable ambient-brain.service
systemctl enable ambient-eyes.service
systemctl enable ambient-dashboard.service

echo "============================================="
echo " SUCCESS! "
echo " The system is now configured to start completely autonomously "
echo " when the Raspberry Pi boots up. "
echo " "
echo " To start them right now without rebooting, run: "
echo " sudo systemctl start ambient-brain ambient-eyes ambient-dashboard "
echo " "
echo " You can access your dashboard from any device on the network at:"
echo " http://<YOUR_PI_IP_ADDRESS>:8501"
echo "============================================="
