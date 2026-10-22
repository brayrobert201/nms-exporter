"""Postgres store for everything that is not in the game's save (the nms-db CNPG cluster,
homelab-k8s infra/nms-db).

The live hook (pymhf_mods/*) runs inside the game and keeps writing its JSONL day files
(trail-, visor-, systems-, weather-YYYYMMDD.jsonl in LIVE_DIR); Ingest copies new complete
lines into the `event` table, exactly once (the file offset is committed in the same
transaction as the rows). Everything the map shows is then read back from here, never from
the files: with the database down the map reports an error rather than serving stale data.
live.json, the 4 Hz current-position file, is the one exception; it is state, not history.

Duplicate visor markers are dropped on the way in: the game re-adds the same marker every time
an area loads (40,468 of 41,760 lines on 2026-10-22), so a marker_add is kept only the first
time its (type, name, position to MARKER_M) is seen.

Connection: libpq's PG* variables (PGHOST, PGPORT, PGDATABASE, PGUSER, PGPASSWORD,
PGSSLMODE), from /etc/nms-exporter/db.env, which nms-bao-sync writes from OpenBao kv/nms-db.
The views at the end of SCHEMA are for ad-hoc SQL (`scripts/nms-sql`).
"""
from __future__ import annotations

import glob
import json
import os
import threading
import time

import psycopg
from psycopg.types.json import Jsonb

STREAMS = ("trail", "visor", "systems", "weather")
MARKER_M = 5.0

SCHEMA_VERSION = 1
SCHEMA = """
CREATE TABLE IF NOT EXISTS schema_version (version int NOT NULL);
CREATE TABLE IF NOT EXISTS event (
    id      bigserial PRIMARY KEY,
    stream  text NOT NULL,             -- trail | visor | systems | weather
    t       double precision NOT NULL, -- unix seconds, as the hook wrote it
    address bigint,                    -- trail: the planet/system (packed like the save's GalacticAddress)
    data    jsonb NOT NULL             -- the hook's line, unchanged
);
CREATE INDEX IF NOT EXISTS event_address ON event (address, t) WHERE address IS NOT NULL;
CREATE INDEX IF NOT EXISTS event_stream_id ON event (stream, id);
CREATE INDEX IF NOT EXISTS event_stream_t ON event (stream, t);
CREATE TABLE IF NOT EXISTS ingest_file (
    path    text PRIMARY KEY,
    pos     bigint NOT NULL,
    updated timestamptz NOT NULL DEFAULT now()
);
-- what Bob recorded on the map (was LIVE_DIR/find_labels.json)
CREATE TABLE IF NOT EXISTS find_label (
    key     text PRIMARY KEY,
    label   jsonb NOT NULL
);
-- each visited planet's resources, biome, weather, colours (was LIVE_DIR/planets.json)
CREATE TABLE IF NOT EXISTS planet_facts (
    address bigint PRIMARY KEY,
    facts   jsonb NOT NULL,
    updated timestamptz NOT NULL DEFAULT now()
);

-- typed views for queries; positions are metres in the planet's frame (centre = 0, +Y = north)
CREATE OR REPLACE VIEW trail AS
SELECT id, to_timestamp(t) AS at, t, address, (address >> 52) & 15 AS planet,
       data->>'location' AS location,
       (data->'rel'->>0)::float8 AS x, (data->'rel'->>1)::float8 AS y, (data->'rel'->>2)::float8 AS z,
       (data->>'distance_from_planet')::float8 AS altitude, (data->>'sealevel')::float8 AS sealevel
FROM event WHERE stream = 'trail';
CREATE OR REPLACE VIEW marker AS
SELECT id, to_timestamp(t) AS at, t, data->>'type' AS type, data->>'name' AS name,
       (data->'rel'->>0)::float8 AS x, (data->'rel'->>1)::float8 AS y, (data->'rel'->>2)::float8 AS z
FROM event WHERE stream = 'visor' AND data->>'event' = 'marker_add';
CREATE OR REPLACE VIEW chat AS
SELECT id, to_timestamp(t) AS at, t, data->>'event' AS command, data->>'class' AS class,
       data->>'resource' AS resource, data->>'name' AS name,
       (data->'rel'->>0)::float8 AS x, (data->'rel'->>1)::float8 AS y, (data->'rel'->>2)::float8 AS z
FROM event WHERE stream = 'visor' AND data->>'event' IN ('label', 'mark');
CREATE OR REPLACE VIEW star_system AS
SELECT id, to_timestamp(t) AS at, data FROM event WHERE stream = 'systems' AND data->>'event' = 'system';
CREATE OR REPLACE VIEW storm AS
SELECT id, to_timestamp(t) AS at, data FROM event WHERE stream = 'weather';
"""

_local = threading.local()


def connect():
    """This thread's connection (autocommit), reconnecting if it was lost."""
    c = getattr(_local, "conn", None)
    if c is None or c.closed or c.broken:
        c = psycopg.connect("", autocommit=True, connect_timeout=5, application_name="nms-exporter")
        _local.conn = c
    return c


def configured() -> bool:
    return bool(os.environ.get("PGHOST"))


def migrate(live_dir: str):
    """Create or update the schema; import planets.json and find_labels.json the first time."""
    c = connect()
    with c.transaction():
        c.execute("SELECT pg_advisory_xact_lock(4207)")
        c.execute(SCHEMA)
        row = c.execute("SELECT max(version) FROM schema_version").fetchone()
        if (row[0] or 0) < SCHEMA_VERSION:
            c.execute("INSERT INTO schema_version VALUES (%s)", (SCHEMA_VERSION,))
        if not c.execute("SELECT 1 FROM planet_facts LIMIT 1").fetchone():
            try:
                with open(os.path.join(live_dir, "planets.json")) as f:
                    for k, v in json.load(f).items():
                        c.execute("INSERT INTO planet_facts (address, facts) VALUES (%s, %s) ON CONFLICT DO NOTHING",
                                  (int(k), Jsonb(v)))
            except (OSError, ValueError):
                pass
        if not c.execute("SELECT 1 FROM find_label LIMIT 1").fetchone():
            try:
                with open(os.path.join(live_dir, "find_labels.json")) as f:
                    for k, v in json.load(f).items():
                        c.execute("INSERT INTO find_label (key, label) VALUES (%s, %s) ON CONFLICT DO NOTHING", (k, Jsonb(v)))
            except (OSError, ValueError):
                pass


def tail(stream: str, after: int, since: float | None = None) -> tuple[int, list[tuple[int | None, dict]]]:
    """Every row of one stream with id > after (and t >= since), oldest first, paged.
    Returns (the last id seen, [(address, the hook's line as a dict)])."""
    c, out = connect(), []
    while True:
        rows = c.execute("SELECT id, address, data FROM event WHERE stream = %s AND id > %s AND t >= %s "
                         "ORDER BY id LIMIT 50000", (stream, after, since or 0)).fetchall()
        if not rows:
            return after, out
        after = rows[-1][0]
        out += [(a, d) for _, a, d in rows]


class Ingest:
    """Copies the hook's day files into `event`. Runs on its own thread every PERIOD_S."""
    PERIOD_S = 2.0

    def __init__(self, live_dir: str):
        self.dir = live_dir
        self.error: str | None = None
        self.last_ok = 0.0
        self._seen: set | None = None      # marker_add keys already stored
        self._centres: dict = {}           # rounded planet centre -> address, from trail lines that had one
        self._lock_conn = None             # the connection holding the writer lock

    @staticmethod
    def ua_int(ua):
        """The hook's address dict packed like the save's GalacticAddress (as live.ua_int)."""
        try:
            x, y, z = ua["voxel"]
            return ((x & 0xFFF) | ((z & 0xFFF) << 12) | ((y & 0xFF) << 24) | (min(ua["reality"], 0xFF) << 32)
                    | (min(ua["system"], 0xFFF) << 40) | (ua["planet"] << 52))
        except (KeyError, TypeError, ValueError):
            return None

    def _address(self, r):
        """A trail line's address: its own, else the planet whose centre it shares (the hook
        sometimes writes ua null; the planet centre identifies the planet within a session)."""
        a = self.ua_int(r.get("ua"))
        pp = r.get("planet_pos")
        key = tuple(round(c) for c in pp) if pp else None
        if a is not None:
            if key and (a >> 52) & 0xF:
                self._centres[key] = a
            return a
        return self._centres.get(key) if key else None

    def _marker_key(self, r):
        rel = r.get("rel") or [0, 0, 0]
        return (r.get("type"), r.get("name")) + tuple(round(c / MARKER_M) for c in rel)

    def _load_seen(self, c):
        self._centres = {tuple(round(v) for v in pp): a for pp, a in c.execute(
            "SELECT DISTINCT ON (data->'planet_pos') data->'planet_pos', address FROM event "
            "WHERE stream = 'trail' AND address IS NOT NULL AND (address >> 52) & 15 > 0 AND data->'planet_pos' IS NOT NULL "
            "ORDER BY data->'planet_pos', id DESC") if pp}
        self._seen = set()
        for (d,) in c.execute("SELECT data FROM event WHERE stream = 'visor' AND data->>'event' = 'marker_add'"):
            self._seen.add(self._marker_key(d))

    def once(self) -> int:
        c = connect()
        # one writer: a second exporter (the dev-deploy test copy on :9878) only reads.
        # A session lock, so it is released when this connection goes.
        if self._lock_conn is not c:
            if not c.execute("SELECT pg_try_advisory_lock(4208)").fetchone()[0]:
                return 0
            self._lock_conn = c
        if self._seen is None:
            self._load_seen(c)
        pos = dict(c.execute("SELECT path, pos FROM ingest_file").fetchall())
        added = 0
        for stream in STREAMS:
            for path in sorted(glob.glob(os.path.join(self.dir, f"{stream}-*.jsonl"))):
                name = os.path.basename(path)
                start = pos.get(name, 0)
                try:
                    if os.path.getsize(path) <= start:
                        continue
                    with open(path, "rb") as f:
                        f.seek(start)
                        data = f.read(64 << 20)
                except OSError:
                    continue
                end = data.rfind(b"\n") + 1          # a half-written last line waits for next time
                if not end:
                    continue
                rows, keys = [], []
                for line in data[:end].splitlines():
                    try:
                        r = json.loads(line)
                        t = float(r["t"])
                    except (ValueError, KeyError, TypeError):
                        continue
                    if stream == "visor" and r.get("event") == "marker_add":
                        k = self._marker_key(r)
                        if k in self._seen or k in keys:
                            continue
                        keys.append(k)
                    rows.append((stream, t, self._address(r) if stream == "trail" else None, Jsonb(r)))
                with c.transaction():
                    if rows:
                        with c.cursor() as cur:
                            cur.executemany("INSERT INTO event (stream, t, address, data) VALUES (%s, %s, %s, %s)", rows)
                    c.execute("INSERT INTO ingest_file (path, pos) VALUES (%s, %s) ON CONFLICT (path) DO UPDATE "
                              "SET pos = excluded.pos, updated = now()", (name, start + end))
                self._seen.update(keys)
                added += len(rows)
        return added

    def run(self):
        while True:
            try:
                n = self.once()
                self.error, self.last_ok = None, time.time()
                if n:
                    print(f"ingest: {n} new rows", flush=True)
            except Exception as e:      # noqa: BLE001 - keep the thread alive; the error is reported on /api/*
                self.error = f"{type(e).__name__}: {e}"
                self._seen = None
                try:
                    _local.conn.close()
                except Exception:       # noqa: BLE001
                    pass
            time.sleep(self.PERIOD_S)

    def start(self):
        threading.Thread(target=self.run, name="nms-ingest", daemon=True).start()


def put_label(key: str, label: dict | None):
    c = connect()
    if label:
        c.execute("INSERT INTO find_label (key, label) VALUES (%s, %s) ON CONFLICT (key) DO UPDATE SET label = excluded.label",
                  (key, Jsonb(label)))
    else:
        c.execute("DELETE FROM find_label WHERE key = %s", (key,))


def labels() -> dict:
    return dict(connect().execute("SELECT key, label FROM find_label").fetchall())


def put_planet(address: int, facts: dict):
    connect().execute("INSERT INTO planet_facts (address, facts) VALUES (%s, %s) ON CONFLICT (address) DO UPDATE "
                      "SET facts = excluded.facts, updated = now()", (address, Jsonb(facts)))


def planets() -> dict:
    return dict(connect().execute("SELECT address, facts FROM planet_facts").fetchall())
