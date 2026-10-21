#!/usr/bin/env python3
"""No Man's Sky exporter: the player's save as Prometheus metrics.

  /metrics  for VictoriaMetrics (projected forward from the save's timestamps)
  /json     the same snapshot as JSON, for the wall displays
  /healthz

Runs as the Steam user, because it reads the Proton save directory. Nothing else
needs to be installed: standard library only.
Standard library only.
"""
from __future__ import annotations

import json
import os
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from nmsexporter.nms import Collector  # noqa: E402

HOST = os.environ.get("NMS_EXPORTER_HOST", "0.0.0.0")
PORT = int(os.environ.get("NMS_EXPORTER_PORT", "9877"))

collector = Collector()


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "nms-exporter"

    def log_message(self, fmt, *args):
        pass

    def _send(self, body: bytes, ctype: str, status: int = 200):
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def do_GET(self):
        path, _, query = self.path.partition("?")
        path = path.rstrip("/") or "/"
        params = dict(p.split("=", 1) for p in query.split("&") if "=" in p)
        try:
            if path in ("/metrics", "/json", "/", "/diff", "/raw/bases"):
                collector.refresh()
            if path == "/metrics":
                return self._send(collector.metrics().encode(), "text/plain; version=0.0.4")
            if path == "/json":
                return self._send(json.dumps(collector.projected()).encode(), "application/json")
            if path == "/diff":
                try:
                    against = int(params.get("against", "1"))
                except ValueError:
                    against = 1
                return self._send(json.dumps(collector.diff(against)).encode(), "application/json")
            if path == "/raw/bases":
                return self._send(json.dumps(collector.raw_bases).encode(), "application/json")
            if path == "/healthz":
                return self._send(b"ok", "text/plain")
            if path == "/":
                return self._send(b"nms-exporter: /metrics /json /diff?against=N /raw/bases /healthz\n", "text/plain")
            self._send(b"not found", "text/plain", 404)
        except BrokenPipeError:
            pass
        except Exception as e:
            try:
                self._send(f"error: {e}\n".encode(), "text/plain", 500)
            except Exception:
                pass

    do_HEAD = do_GET


def main():
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    server.daemon_threads = True
    print(f"nms-exporter listening on http://{HOST}:{PORT}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
