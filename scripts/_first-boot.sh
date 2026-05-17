#!/bin/bash
# _first-boot.sh — Run ONCE on the Mac mini's Terminal at first boot.
# Installs the laptop's SSH pubkey + kicks off the full bootstrap.
#
# Usage on the mini:
#   curl -s http://192.168.7.95:8000/_first-boot.sh | bash

set -uo pipefail

LAPTOP="http://192.168.7.95:8000"

echo "[first-boot] installing laptop pubkey into authorized_keys"
mkdir -p ~/.ssh
chmod 700 ~/.ssh
curl -fsS "$LAPTOP/laptop-pubkey" >> ~/.ssh/authorized_keys
chmod 600 ~/.ssh/authorized_keys
echo "[first-boot] ✓ pubkey installed"

echo "[first-boot] downloading bootstrap"
curl -fsS "$LAPTOP/macmini-bootstrap.sh" -o ~/macmini-bootstrap.sh
chmod +x ~/macmini-bootstrap.sh
echo "[first-boot] ✓ bootstrap downloaded"

echo "[first-boot] running bootstrap (this will prompt for your password for sudo)"
echo "[first-boot] total runtime ~20-30 min — model pull is the long step"
echo "[first-boot] you can leave it running and check back"
echo ""
bash ~/macmini-bootstrap.sh 2>&1 | tee ~/bootstrap.log
