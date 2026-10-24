#!/usr/bin/env python3
"""No Man's Sky exporter: the player's save as Prometheus metrics.

  /metrics  for VictoriaMetrics (projected forward from the save's timestamps)
  /json     the same snapshot as JSON, for the wall displays
  /healthz

Runs as the Steam user, because it reads the Proton save directory. The save
side is standard library only; the map's history (trail, finds, systems) lives in
Postgres (nms-db, see nmsexporter/db.py), reached with psycopg from the project's
uv environment (pyproject.toml). With nms-db down, /metrics and /json carry on and
the map's history APIs answer 503 with the reason.
"""
from __future__ import annotations

import json
import os
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from urllib.parse import unquote_plus  # noqa: E402

import psycopg  # noqa: E402

from nmsexporter import db, maps  # noqa: E402
from nmsexporter.live import LIVE_DIR, Live  # noqa: E402
from nmsexporter.systems import portal  # noqa: E402
from nmsexporter.nms import Collector  # noqa: E402

HOST = os.environ.get("NMS_EXPORTER_HOST", "0.0.0.0")
PORT = int(os.environ.get("NMS_EXPORTER_PORT", "9877"))

ICON_DIR = os.environ.get("NMS_ICON_DIR", os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "icons"))
GLYPH_DIR = os.environ.get("NMS_GLYPH_DIR", os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "glyphs"))
_HERE = os.path.dirname(os.path.abspath(__file__))
_FONT_TYPES = {"woff2": "font/woff2", "ttf": "font/ttf", "txt": "text/plain"}
FONT_DIRS = ((os.path.join(_HERE, "nmsexporter", "web", "fonts"), _FONT_TYPES), (os.path.join(_HERE, "conky", "fonts"), _FONT_TYPES))
collector = Collector()
live = Live()
ingest = db.Ingest(LIVE_DIR)
# routes whose whole answer lives in nms-db; /api/live is not one: the position is a file and
# live.build reports the database's state in its own `db` field
DB_PATHS = ("/api/elevation", "/api/finds", "/api/sectors", "/api/systems")


def db_error() -> str | None:
    """Why the map's history is unavailable, or None."""
    if not db.configured():
        return "nms-db not configured: no PGHOST (nms-bao-sync writes /etc/nms-exporter/db.env)"
    return ingest.error


def start_db():
    """Create the schema, then copy the hook's files in every 2 s. Retries until nms-db answers."""
    if not db.configured():
        print("nms-db not configured (no PGHOST): the map's history APIs will answer 503", flush=True)
        return

    def run():
        while True:
            try:
                db.migrate(ingest.dir)
                break
            except Exception as e:      # noqa: BLE001
                ingest.error = f"{type(e).__name__}: {e}"
                print(f"nms-db: {ingest.error}; retrying in 30 s", flush=True)
                time.sleep(30)
        print("nms-db: schema ready, ingesting", flush=True)
        ingest.run()
    threading.Thread(target=run, name="nms-db", daemon=True).start()


def page_html(name: str) -> bytes:
    """Read on each request so an edited page needs no restart."""
    with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "nmsexporter", "web", name), "rb") as f:
        return f.read()


def map_html() -> bytes:
    return page_html("map.html")


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
            if path in DB_PATHS and not db.configured():
                return self._send(json.dumps({"error": db_error(), "db": False}).encode(), "application/json", 503)
            if path in ("/metrics", "/json", "/", "/diff", "/raw/bases", "/api/craft", "/api/map", "/api/live", "/api/elevation", "/api/finds", "/api/systems", "/api/sectors"):
                collector.refresh()
            if path == "/metrics":
                up = 0 if db_error() else 1
                extra = ("# HELP nms_db_up 1 when nms-db (the map's history store) is reachable and ingesting\n"
                         f"# TYPE nms_db_up gauge\nnms_db_up {up}\n")
                return self._send((collector.metrics() + extra).encode(), "text/plain; version=0.0.4")
            if path == "/json":
                return self._send(json.dumps(collector.projected()).encode(), "application/json")
            if path == "/diff":
                try:
                    against = int(params.get("against", "1"))
                except ValueError:
                    against = 1
                return self._send(json.dumps(collector.diff(against)).encode(), "application/json")
            if path == "/api/craft":
                # every level of building, and the build order: ?id=<id or name>&n=<units>, or several
                # together sharing the stock: ?items=ULTRAPROD1:8,ULTRAPROD2:8
                targets = []
                for part in unquote_plus(params.get("items", "")).split(","):
                    iid, _, q = part.rpartition(":") if ":" in part else (part, "", "1")
                    if iid.strip():
                        targets.append((iid.strip(), int(q) if q.strip().isdigit() else 1))
                if not targets and params.get("id"):
                    n = params.get("n", "1")
                    targets = [(unquote_plus(params["id"]), int(n) if n.isdigit() else 1)]
                out = collector.craft_tree(targets)
                return self._send(json.dumps(out).encode(), "application/json", 404 if "error" in out else 200)
            if path == "/raw/bases":
                return self._send(json.dumps(collector.raw_bases).encode(), "application/json")
            if path == "/api/map":
                m = maps.build(collector.raw_points, collector.raw_bases, collector.tables)
                try:
                    if not db.configured():
                        raise psycopg.OperationalError(db_error())
                    m["planets"] += live.visited_planets(collector.raw_bases)
                    live.systems.refresh()
                except psycopg.Error as e:
                    # the save's planets and bases still show; planets known only from the hook do not
                    m.setdefault("errors", {})["nms-db"] = f"nms-db unreachable: {e}".strip()
                for pl in m["planets"]:
                    a = maps._addr(pl.get("address"))
                    pl["planet_name"], pl["system_name"] = live.systems.planet_name(a), live.systems.system_name(a)
                    pl["portal"] = portal(a) if a is not None else None
                    pl["tile_colours"] = (live.finds.planets.get(a) or {}).get("tile_colours") if a is not None else None
                return self._send(json.dumps(m).encode(),
                                  "application/json")
            if path == "/api/live":
                return self._send(json.dumps(live.build(collector.raw_bases, unquote_plus(params.get("base", "")) or None,
                                                        unquote_plus(params.get("target", "")) or None,
                                                        items=collector.tables.get("items"), tables=collector.tables)).encode(),
                                  "application/json")
            if path == "/api/systems":
                live.systems.refresh()
                runes = (collector.raw_points or {}).get("known_runes")
                return self._send(json.dumps({"systems": live.systems.listing(maps._addr(unquote_plus(params.get("from", ""))),
                                                                              collector.raw_bases, runes),
                                              "known_runes": runes, "ly_per_voxel": 400}).encode(), "application/json")
            if path.startswith("/icon/") and path.endswith(".png"):
                # the game's HUD icons, extracted by scripts/nms-icons (not in the repo)
                n = path[len("/icon/"):-len(".png")]
                if n and all(c.isalnum() or c in "._" for c in n) and ".." not in n:
                    try:
                        with open(os.path.join(ICON_DIR, f"{n}.png"), "rb") as f:
                            return self._send(f.read(), "image/png")
                    except OSError:
                        pass
                return self._send(b"no icon (run scripts/nms-icons)", "text/plain", 404)
            if path.startswith("/glyph/") and path.endswith(".png"):
                # portal glyph icons extracted from the game by scripts/nms-glyphs (not in the repo)
                h = path[len("/glyph/"):-len(".png")].lower()
                if len(h) == 1 and h in "0123456789abcdef":
                    try:
                        with open(os.path.join(GLYPH_DIR, f"{h}.png"), "rb") as f:
                            return self._send(f.read(), "image/png")
                    except OSError:
                        pass
                return self._send(b"no glyph (run scripts/nms-glyphs)", "text/plain", 404)
            if path == "/systems":
                return self._send(page_html("systems.html"), "text/html; charset=utf-8")
            if path == "/api/finds":
                return self._send(json.dumps(live.finds_api(collector.raw_bases, maps._addr(unquote_plus(params.get("address", ""))),
                                                            unquote_plus(params.get("base", "")) or None, collector.tables)).encode(),
                                  "application/json")
            if path == "/api/sectors":
                return self._send(json.dumps(live.sectors(collector.raw_bases, maps._addr(unquote_plus(params.get("address", ""))),
                                                          collector.tables)).encode(), "application/json")
            if path == "/api/elevation":
                try:
                    cell = min(max(float(params.get("cell", "25")), 2.0), 500.0)
                except ValueError:
                    cell = 25.0
                return self._send(json.dumps(live.elevation(collector.raw_bases, maps._addr(unquote_plus(params.get("address", ""))),
                                                            unquote_plus(params.get("base", "")) or None, cell)).encode(),
                                  "application/json")
            if path == "/map":
                return self._send(map_html(), "text/html; charset=utf-8")
            if path == "/mobile":
                # the phone page (android/ wraps it as an app): map, farms, inventory, build
                return self._send(page_html("mobile.html"), "text/html; charset=utf-8")
            if path.startswith("/fonts/"):
                # Geist (nmsexporter/web/fonts, OFL) and the portal glyph font (conky/fonts) for the phone page
                n = path[len("/fonts/"):]
                if n and all(c.isalnum() or c in "._-" for c in n) and ".." not in n:
                    for d, ctype in FONT_DIRS:
                        try:
                            with open(os.path.join(d, n), "rb") as f:
                                body = f.read()
                        except OSError:
                            continue
                        self.send_response(200)
                        self.send_header("Content-Type", ctype.get(n.rsplit(".", 1)[-1].lower(), "application/octet-stream"))
                        self.send_header("Content-Length", str(len(body)))
                        self.send_header("Cache-Control", "public, max-age=86400")
                        self.end_headers()
                        if self.command != "HEAD":
                            self.wfile.write(body)
                        return
                return self._send(b"no such font", "text/plain", 404)
            if path == "/healthz":
                return self._send(b"ok", "text/plain")
            if path == "/" and "text/html" in (self.headers.get("Accept") or ""):
                # a browser at the bare hostname (nms-map.bobs.toys) gets the map
                self.send_response(302)
                self.send_header("Location", "/map")
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            if path == "/":
                return self._send(b"nms-exporter: /metrics /json /diff?against=N /raw/bases /api/craft?id=&n=|items= /map /mobile /api/map /api/live /api/elevation /api/finds /api/sectors /systems /api/systems /healthz\n", "text/plain")
            self._send(b"not found", "text/plain", 404)
        except BrokenPipeError:
            pass
        except psycopg.Error as e:
            try:
                self._send(json.dumps({"error": f"nms-db unreachable: {e}".strip(), "db": False}).encode(), "application/json", 503)
            except Exception:
                pass
        except Exception as e:
            try:
                self._send(f"error: {e}\n".encode(), "text/plain", 500)
            except Exception:
                pass

    do_HEAD = do_GET

    def do_POST(self):
        path = self.path.partition("?")[0].rstrip("/")
        try:
            body = json.loads(self.rfile.read(min(int(self.headers.get("Content-Length") or 0), 4096)) or b"{}")
        except (ValueError, OSError):
            return self._send(b"bad json", "text/plain", 400)
        if path == "/api/finds/class":
            # the player records a hotspot's class from the visor (the marker does not carry it readably)
            try:
                live.elev.refresh()
                live.finds.refresh(live.elev.timeline)
                fields = {k: (body.get(k) or None) for k in ("class", "resource") if k in body}
                ok = bool(fields) and live.finds.set_label(str(body.get("key", "")), **fields)
            except psycopg.Error as e:
                return self._send(json.dumps({"ok": False, "error": f"nms-db unreachable: {e}"}).encode(), "application/json", 503)
            return self._send(json.dumps({"ok": ok}).encode(), "application/json", 200 if ok else 400)
        self._send(b"not found", "text/plain", 404)


def main():
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    server.daemon_threads = True
    start_db()
    print(f"nms-exporter listening on http://{HOST}:{PORT}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
