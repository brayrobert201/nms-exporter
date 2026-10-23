#!/usr/bin/env bash
# Test the working tree on a scratch port, optionally render the right wall
# screen, then install to /opt and reload the live service and conky screens.
#
#   scripts/dev-deploy.sh            # test, install, reload
#   scripts/dev-deploy.sh --render   # also render conky/right.conf in Xvfb to /tmp/nmstest/right.png
#   scripts/dev-deploy.sh --test     # test only, leave the live service alone
#
# The test exporter is found and stopped by its port, never by a process
# pattern, so the live nms-exporter@bob service is never matched by mistake.
set -u
HERE=$(cd "$(dirname "$0")/.." && pwd)
PORT=${NMS_TEST_PORT:-9878}
T=/tmp/nmstest
mkdir -p "$T"
RENDER=0; TESTONLY=0
for a in "$@"; do case "$a" in --render) RENDER=1;; --test) TESTONLY=1;; esac; done

stop_test() {
  local pid
  pid=$(ss -ltnp 2>/dev/null | awk -v p=":$PORT " 'index($0,p){match($0,/pid=([0-9]+)/,m); print m[1]}' | head -1)
  [ -n "${pid:-}" ] && kill "$pid" 2>/dev/null && echo "stopped test exporter (pid $pid)"
}

echo "== syntax"
"$HERE"/.venv/bin/python -m py_compile "$HERE"/nms_exporter.py "$HERE"/nmsexporter/*.py "$HERE"/conky/nms_conky.py || exit 1

echo "== test exporter on :$PORT"
stop_test
rm -f "$T/state.json"
(cd "$HERE" && NMS_EXPORTER_PORT=$PORT NMS_STATE="$T/state.json" nohup "$HERE"/.venv/bin/python nms_exporter.py > "$T/exporter.log" 2>&1 &)
for i in $(seq 1 20); do curl -fs "http://127.0.0.1:$PORT/healthz" >/dev/null 2>&1 && break; sleep 1; done
curl -fs "http://127.0.0.1:$PORT/json" -o "$T/live.json" || { echo "test exporter did not answer"; tail -5 "$T/exporter.log"; stop_test; exit 1; }
python3 - "$T/live.json" <<'EOF' || { stop_test; exit 1; }
import json, sys
d = json.load(open(sys.argv[1]))
errs = d.get("errors") or {}
print("errors:", errs or "none")
print("farms:", len(d.get("farms") or {}), "refiners:", len(d.get("refiners") or []), "items:", len(d.get("items") or {}),
      "planner:", (d.get("planner") or {}).get("best_now", {}).get("counts"))
sys.exit(1 if errs else 0)
EOF
curl -fs "http://127.0.0.1:$PORT/metrics" | grep -c "^nms_" | sed 's/^/metrics: /'

if [ "$RENDER" = 1 ]; then
  echo "== render right screen"
  mkdir -p "$T/xdg" && chmod 700 "$T/xdg"
  (cd "$HERE/conky" && XDG_RUNTIME_DIR="$T/xdg" NMS_CONKY_URL="http://127.0.0.1:$PORT/json" \
    xvfb-run -a -s "-screen 0 2160x3840x24 -dpi 96" sh -c 'conky -c right.conf >'"$T"'/conky.log 2>&1 & CP=$!; sleep 25; import -window root '"$T"'/right.png; kill $CP' >/dev/null 2>&1)
  pgrep -f "nms_search.py --watch" | xargs -r kill 2>/dev/null
  [ -s "$T/right.png" ] && echo "rendered $T/right.png" || echo "render failed, see $T/conky.log"
fi

stop_test
[ "$TESTONLY" = 1 ] && exit 0

echo "== install"
(cd "$HERE" && sudo -n ./install.sh) || exit 1
sleep 5
curl -fs http://127.0.0.1:9877/healthz >/dev/null && echo "live 9877 ok" || { echo "live service not answering"; exit 1; }
pkill -USR1 -f "conky -c /opt/nms-exporter/conky/" && echo "conky reloaded" || echo "no conky running to reload"
