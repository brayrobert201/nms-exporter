"""Live player position for /api/live, from the pyMHF mod
pymhf_mods/live_position.py (live.json plus daily trail-YYYYMMDD.jsonl).

Frames (research/sources/measurements/2026-10-22-live-position-compass.md):
`rel` = player minus nearest planet centre, the same planet-centred frame as a
base's Position; facing is -at; north = planet +Y, east = north x up.

The planet is matched by exact universe address: the mod's galactic address
packed the way the save packs GalacticAddress. Distances between two points
on a planet are along the surface (arc at the player's radius) with heights
apart, so they stay right for a base on the far side of the planet.

Standard library only. Every read returns (value, error) and never raises.
"""
from __future__ import annotations

import json
import math
import os
import time
from collections import deque

from . import maps

LIVE_DIR = os.environ.get("NMS_LIVE_DIR", os.path.expanduser(
    "~/.local/share/Steam/steamapps/compatdata/275850/pfx/drive_c/pymhf/mod_saves/live"))
STALE_S = 10          # older than this, the game or the mod has stopped
NEARBY = 12
PER_KIND = 3
TRAIL_KEEP = 20000
# Kinds left out of the nearby list (still drawn on the map): walls, floors, decor.
NOT_NEARBY = {"structure"}


def ua_int(ua: dict | None) -> int | None:
    """The mod's address dict packed like the save's GalacticAddress (nmspy to_UA)."""
    if not ua:
        return None
    try:
        x, y, z = ua["voxel"]
        return ((x & 0xFFF) | ((z & 0xFFF) << 12) | ((y & 0xFF) << 24) | (min(ua["reality"], 0xFF) << 32)
                | (min(ua["system"], 0xFFF) << 40) | (ua["planet"] << 52))
    except (KeyError, TypeError, ValueError):
        return None


def read_sample():
    try:
        with open(os.path.join(LIVE_DIR, "live.json")) as f:
            return json.load(f), None
    except FileNotFoundError:
        return None, f"no live.json in {LIVE_DIR} (game not hooked with scripts/nms-hook?)"
    except (OSError, ValueError) as e:
        return None, f"live.json: {e}"


class Trail:
    """Today's and yesterday's trail files, read incrementally."""

    def __init__(self):
        self.points: deque = deque(maxlen=TRAIL_KEEP)   # (t, address, rel)
        self._pos: dict[str, int] = {}

    def _files(self):
        now = time.time()
        days = [time.strftime("%Y%m%d", time.localtime(now - 86400)), time.strftime("%Y%m%d", time.localtime(now))]
        return [os.path.join(LIVE_DIR, f"trail-{d}.jsonl") for d in days]

    def refresh(self):
        for path in self._files():
            try:
                with open(path, "rb") as f:
                    f.seek(self._pos.get(path, 0))
                    data = f.read()
            except OSError:
                continue
            end = data.rfind(b"\n") + 1       # leave a half-written last line for next time
            self._pos[path] = self._pos.get(path, 0) + end
            for line in data[:end].splitlines():
                try:
                    s = json.loads(line)
                    self.points.append((s["t"], ua_int(s.get("ua")), s["rel"]))
                except (ValueError, KeyError, TypeError):
                    continue

    def on(self, address: int, since: float):
        return [p[2] for p in self.points if p[1] == address and p[0] >= since]


def _norm(v):
    n = math.sqrt(sum(x * x for x in v))
    return [x / n for x in v] if n else None


def _dot(a, b):
    return sum(x * y for x, y in zip(a, b))


def heading_deg(up, at) -> float | None:
    north, east = maps.tangent_frame(up)
    face = [-x for x in at]
    d = _dot(face, up)
    f = _norm([face[i] - d * up[i] for i in range(3)])
    if not f:
        return None
    return (math.degrees(math.atan2(_dot(f, east), _dot(f, north))) + 360) % 360


def nav(rel, heading, w) -> dict:
    """Distance along the surface, compass bearing, turn (negative = left) and
    height from the player at `rel` to the planet-frame point `w`."""
    u1, u2 = _norm(rel), _norm(w)
    r = math.hypot(*rel)
    c = max(-1.0, min(1.0, _dot(u1, u2)))
    dist = r * math.acos(c)
    north, east = maps.tangent_frame(u1)
    t = _norm([u2[i] - c * u1[i] for i in range(3)])
    bearing = (math.degrees(math.atan2(_dot(t, east), _dot(t, north))) + 360) % 360 if t else 0.0
    turn = None if heading is None else ((bearing - heading + 540) % 360) - 180
    return {"dist": round(dist, 1), "bearing": round(bearing, 1),
            "turn": None if turn is None else round(turn, 1), "h": round(math.hypot(*w) - r, 1)}


class Live:
    def __init__(self):
        self.trail = Trail()
        self._objs_for = None
        self._objs: dict = {}      # address -> [(key, base, kind, id, world)]

    def _objects(self, bases):
        """World positions of every built object, per planet; rebuilt when the save is re-read."""
        if self._objs_for is bases:
            return self._objs
        out: dict = {}
        for b in bases:
            t = (b.get("BaseType") or {}).get("PersistentBaseTypes")
            if t in maps.SKIP_BASES or not b.get("Position"):
                continue
            frame = maps.base_en(b)
            if not frame:
                continue
            name = b.get("Name") or "base"
            lst = out.setdefault(maps._addr(b.get("GalacticAddress")), [])
            lst.append((f"b:{name}", name, "base", name, list(b["Position"][:3])))
            for i, o in enumerate(b.get("Objects") or []):
                oid = o.get("ObjectID") or ""
                p = o.get("Position")
                if not p or oid in maps.SEGMENTS or oid == "^BASE_FLAG":
                    continue
                lst.append((f"o:{name}:{i}", name, maps._kind(oid), oid.lstrip("^"), maps.local_to_world(b, frame[0], p)))
        self._objs_for, self._objs = bases, out
        return out

    def build(self, bases: list, base: str | None = None, target: str | None = None, trail_s: float = 6 * 3600) -> dict:
        sample, err = read_sample()
        if sample is None:
            return {"state": "none", "error": err}
        age = time.time() - sample.get("t", 0)
        out = {"state": "stale" if age > STALE_S else "live", "age": round(age, 1),
               "location": sample.get("location"), "error": None}
        address = ua_int(sample.get("ua"))
        out["address"] = f"0x{address:X}" if address is not None else None
        rel, at = sample.get("rel"), sample.get("at")
        mine = [b for b in bases if maps._addr(b.get("GalacticAddress")) == address and b.get("Position")
                and (b.get("BaseType") or {}).get("PersistentBaseTypes") not in maps.SKIP_BASES]
        if not mine or not rel or not at or not sample.get("in_atmosphere") and sample.get("distance_from_planet", 1e9) > 20000:
            out["on_planet"] = False
            out["why"] = ("no address yet" if address is None else
                          "no bases on this planet" if not mine else "not near the planet surface")
            return out
        out["on_planet"] = True
        up = _norm(rel)
        heading = heading_deg(up, at)
        proj = maps.planet_projection(mine)
        x, y = proj.xy(rel)
        lat, lon = maps.latlon(rel)
        out["player"] = {"x": round(x, 1), "y": round(y, 1), "heading": None if heading is None else round(heading, 1),
                         "lat": lat, "lon": lon, "w": [round(c, 1) for c in rel]}

        self.trail.refresh()
        tr = self.trail.on(address, time.time() - trail_s)
        out["trail"] = [[round(a, 1), round(b, 1)] for a, b in (proj.xy(p) for p in tr[-4000:])]

        bframe = None
        if base:
            b = next((b for b in mine if (b.get("Name") or "base") == base), None)
            frame = maps.base_en(b) if b else None
            if frame:
                axes, en = frame
                bframe = (b, axes, en)
                e, n, h = en(maps.world_to_local(b, axes, rel))
                out["in_base"] = {"name": base, "e": e, "n": n, "h": h,
                                  "trail": [list(en(maps.world_to_local(b, axes, p))[:2]) for p in tr[-4000:]]}

        objs = self._objects(bases).get(address, [])
        rows = []
        for key, bname, kind, oid, w in objs:
            if kind in NOT_NEARBY:
                continue
            nv = nav(rel, heading, w)
            rows.append((nv["dist"], {"key": key, "base": bname, "kind": kind, "id": oid, **nv}))
        rows.sort(key=lambda r: r[0])
        per_kind: dict = {}
        near = []
        for _, r in rows:                     # nearest few of each kind, so twelve depots don't fill it
            if per_kind.get(r["kind"], 0) < PER_KIND:
                per_kind[r["kind"]] = per_kind.get(r["kind"], 0) + 1
                near.append(r)
            if len(near) == NEARBY:
                break
        out["nearby"] = near
        out["bases"] = sorted((r[1] for r in rows if r[1]["kind"] == "base"), key=lambda r: r["dist"])

        if target:
            w = None
            if target.startswith("w:"):
                try:
                    w = [float(c) for c in target[2:].split(",")][:3]
                except ValueError:
                    w = None
            else:
                w = next((o[4] for o in objs if o[0] == target), None)
            if w and len(w) == 3:
                tx, ty = proj.xy(w)
                out["target"] = {"key": target, "x": round(tx, 1), "y": round(ty, 1), **nav(rel, heading, w)}
                if bframe:
                    te, tn, _ = bframe[2](maps.world_to_local(bframe[0], bframe[1], w))
                    out["target"].update(e=te, n=tn)
            else:
                out["target"] = {"key": target, "error": "not on this planet"}
        return out
