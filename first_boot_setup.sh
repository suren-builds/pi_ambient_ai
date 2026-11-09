#!/bin/bash
# first_boot_setup.sh — Run this ONCE on the Pi after first boot.
# It moves the project from /boot/firmware/ambient_ai to ~/ambient_ai
# then runs the full setup automatically.
#
# Usage (on Pi, from any directory):
#   bash /boot/firmware/ambient_ai/first_boot_setup.sh

set -euo pipefail

echo "============================================="
echo "  AMBIENT AI HUB - FIRST BOOT SETUP         "
echo "============================================="

SRC="/boot/firmware/ambient_ai"
DEST="$HOME/ambient_ai"

# ── Move project from boot partition to home ──────────────────
if [ ! -d "$SRC" ]; then
    # Some Pi OS versions mount boot at /boot instead of /boot/firmware
    SRC="/boot/ambient_ai"
fi

if [ ! -d "$SRC" ]; then
    echo "[ERROR] Could not find project at /boot/firmware/ambient_ai or /boot/ambient_ai"
    echo "        Make sure the SD card was written correctly."
    exit 1
fi

echo "[1/3] Moving project to $DEST ..."
if [ -d "$DEST" ]; then
    echo "      $DEST already exists — backing up to ${DEST}.bak"
    mv "$DEST" "${DEST}.bak"
fi
cp -r "$SRC" "$DEST"
echo "      Done. Project is now at $DEST"

# Fix line endings in shell scripts (Windows CRLF → Unix LF)
echo "[2/3] Fixing line endings in shell scripts..."
if command -v dos2unix &>/dev/null; then
    dos2unix "$DEST"/*.sh
else
    for f in "$DEST"/*.sh; do
        sed -i 's/\r//' "$f"
    done
fi
chmod +x "$DEST"/*.sh

# ── Run the full setup ────────────────────────────────────────
echo "[3/3] Running setup_pi.sh ..."
cd "$DEST"
bash setup_pi.sh

echo ""
echo "============================================="
echo " FIRST BOOT SETUP COMPLETE!                 "
echo "                                            "
echo " Next steps:                                "
echo "   1. Plug in your USB camera               "
echo "   2. Run face enrollment:                  "
echo "      cd ~/ambient_ai                       "
echo "      source .venv/bin/activate             "
echo "      python3 enroll_owner.py               "
echo "   3. Install auto-start services:          "
echo "      sudo ./install_services.sh            "
echo "   4. Start services now:                   "
echo "      sudo systemctl start ambient-brain \  "
echo "                       ambient-eyes \       "
echo "                       ambient-dashboard    "
echo "   5. Open on your phone:                   "
echo "      http://$(hostname -I | awk '{print $1}'):8501"
echo "============================================="
