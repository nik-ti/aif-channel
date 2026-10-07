#!/usr/bin/env bash
# Install (or re-install) AI Flow's two services and its log rotation.
# Run: sudo bash deploy/install.sh
# Check it first by hand: python3 main.py check
set -euo pipefail

PROJECT_DIR="/home/nikita/systems/aif-channel"

[ -f "${PROJECT_DIR}/.env" ] || { echo "No .env: copy .env.example to .env and fill it in."; exit 1; }
sudo -u nikita python3 "${PROJECT_DIR}/main.py" check

for unit in aif-channel aif-dashboard-api; do
    install -m 644 "${PROJECT_DIR}/deploy/${unit}.service" "/etc/systemd/system/${unit}.service"
done
install -m 644 "${PROJECT_DIR}/deploy/aif-channel.logrotate" /etc/logrotate.d/aif-channel
systemctl daemon-reload
systemctl enable --now aif-channel aif-dashboard-api
systemctl --no-pager status aif-channel aif-dashboard-api | grep -E "●|Active:"
