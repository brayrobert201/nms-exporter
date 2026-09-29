#!/usr/bin/env bash
# Install the exporter to /opt/nms-exporter and start it for the Steam user.
# Run as root: sudo ./install.sh            (Steam user = whoever ran sudo)
#              sudo NMS_USER=alice ./install.sh
set -euo pipefail
cd "$(dirname "$0")"
[[ $EUID -eq 0 ]] || { echo "run as root" >&2; exit 1; }
NMS_USER="${NMS_USER:-${SUDO_USER:-}}"
[[ -n "$NMS_USER" ]] || { echo "set NMS_USER to the Steam user" >&2; exit 1; }

DEST=/opt/nms-exporter
install -d "$DEST"
cp -r nms_exporter.py nmsexporter data "$DEST/"
chmod 755 "$DEST/nms_exporter.py"
install -m 644 systemd/nms-exporter@.service /etc/systemd/system/nms-exporter@.service
systemctl daemon-reload
systemctl enable --now "nms-exporter@${NMS_USER}.service"
systemctl restart "nms-exporter@${NMS_USER}.service"
echo "nms-exporter@${NMS_USER} running: http://127.0.0.1:9877/metrics"
