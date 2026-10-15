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
cp -r nms_exporter.py nmsexporter data conky "$DEST/"
chmod 755 "$DEST/nms_exporter.py"
install -m 644 systemd/nms-exporter@.service /etc/systemd/system/nms-exporter@.service
install -m 644 systemd/nms-conky@.service /etc/systemd/user/nms-conky@.service
# portal glyph font for the traveller screen (see conky/fonts/NOTICE.md)
install -D -m 644 conky/fonts/NMS-Glyphs-Mono.ttf /usr/local/share/fonts/nms/NMS-Glyphs-Mono.ttf
fc-cache -f /usr/local/share/fonts/nms >/dev/null 2>&1 || true
systemctl daemon-reload
systemctl enable --now "nms-exporter@${NMS_USER}.service"
systemctl restart "nms-exporter@${NMS_USER}.service"
echo "nms-exporter@${NMS_USER} running: http://127.0.0.1:9877/metrics"
echo "Optional wall screens (apt install conky-all), as ${NMS_USER} in the desktop session:"
echo "  ./scripts/apply-kwin-rules.sh"
echo "  systemctl --user enable --now nms-conky@left nms-conky@right"
