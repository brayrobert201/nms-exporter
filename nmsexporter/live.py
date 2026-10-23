"""Live player position for /api/live, from the pyMHF mod
pymhf_mods/live_position.py: live.json for where the player is now, and the
trail (its daily trail-YYYYMMDD.jsonl, copied into nms-db by db.Ingest) for
where they have been.

Frames (research/sources/measurements/2026-10-22-live-position-compass.md):
`rel` = player minus nearest planet centre, the same planet-centred frame as a
base's Position; facing is -at; north = planet +Y, east = north x up.

The planet is matched by exact universe address: the mod's galactic address
packed the way the save packs GalacticAddress. Distances between two points
on a planet are along the surface (arc at the player's radius) with heights
apart, so they stay right for a base on the far side of the planet.

live.json reads return (value, error) and never raise; history reads go to
nms-db and raise when it is unreachable (the HTTP handler reports that).
"""
from __future__ import annotations

import json
import math
import os
import time
import urllib.request
from collections import Counter, deque

import psycopg

from . import db, maps, sectors
from .finds import Finds
from .systems import Systems

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


# live_position 0.5 serves the latest sample through pyMHF's HTTP API; NMS_LIVE_URL="" turns it off.
LIVE_URL = os.environ.get("NMS_LIVE_URL", "http://127.0.0.1:5000/LivePosition/sample")


def _sample_over_http():
    """The mod's current sample from pyMHF's HTTP API, or None (no game, older mod, no http_api)."""
    if not LIVE_URL:
        return None
    try:
        with urllib.request.urlopen(LIVE_URL, timeout=0.3) as r:
            s = json.loads(r.read())
        return s if isinstance(s, dict) and s.get("t") else None
    except (OSError, ValueError):
        return None


def read_sample():
    """The latest sample: from pyMHF's HTTP API when it answers, else live.json (attach-mode
    sessions and mods older than 0.5). Returns (value, error) and never raises."""
    s = _sample_over_http()
    if s is not None:
        return s, None
    try:
        with open(os.path.join(LIVE_DIR, "live.json")) as f:
            return json.load(f), None
    except FileNotFoundError:
        return None, f"no live.json in {LIVE_DIR} (game not hooked with scripts/nms-hook?)"
    except (OSError, ValueError) as e:
        return None, f"live.json: {e}"


class Trail:
    """The last two days of trail, from nms-db (db.py), read incrementally."""

    def __init__(self):
        self.points: deque = deque(maxlen=TRAIL_KEEP)   # (t, address, rel)
        self._last = 0

    def refresh(self):
        self._last, rows = db.tail("trail", self._last, None if self._last else time.time() - 2 * 86400)
        for address, s in rows:
            if s.get("rel"):
                self.points.append((s["t"], address, s["rel"]))

    def on(self, address: int, since: float):
        return [p[2] for p in self.points if p[1] == address and p[0] >= since]


def _norm(v):
    n = math.sqrt(sum(x * x for x in v))
    return [x / n for x in v] if n else None


def _dot(a, b):
    return sum(x * y for x, y in zip(a, b))


# mPlayerTM.at points behind the player on foot but ahead in a ship: over the trail,
# movement vs at averaged cos -0.94 on foot (304 steps) and +0.99 flying or landed
# in the ship (1042 steps, locations PlanetInShip and Default). The corvette
# interior ("Freighter") and Underwater were mixed and stay with the on-foot sign.
# nmspy EnvironmentLocation has no "in space in ship" value: flying in space reports Default
# (0x1), landed or flying over a planet PlanetInShip (0x4). In both, `at` points forward.
SHIP_LOCATIONS = {"PlanetInShip", "Default"}


def heading_deg(up, at, location: str | None = None) -> float | None:
    north, east = maps.tangent_frame(up)
    face = list(at) if location in SHIP_LOCATIONS else [-x for x in at]
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


# Ground elevation from where the player has been. distance_from_planet is the
# height above the planet's nominal radius: |rel| - distance_from_planet is the
# same round number for every sample on a planet (130048 = 127 x 1024, 98304 =
# 96 x 1024). `sealevel` is where the water surface sits above that radius: 120 on
# Activated Indium's water planet, 0 on every dry planet seen, so a planet with
# sealevel 0 is taken to have no sea. On foot or in an exocraft the player is on
# the ground; indoors (floors), caves, swimming and ships are not used. A cell
# keeps its lowest sample, so jetpack jumps don't raise it.
GROUND_LOCATIONS = {"PlanetOnFoot", "PlanetInVehicle"}
# Built objects that stand on the ground give heights at bases too.
GROUND_KINDS = {"extractor-mineral", "extractor-gas", "depot", "power", "computer", "teleporter"}


class Elevation:
    """Every trail file ever written, read incrementally: ground samples and
    the nominal radius of each planet seen."""

    def __init__(self):
        self.samples: dict = {}     # address -> [rel]
        self.radius: dict = {}      # address -> nominal radius (the value most samples agree on)
        self._radii: dict = {}      # address -> Counter of |rel| - distance_from_planet
        self.water: dict = {}       # address -> water surface above the nominal radius (absent: no sea seen)
        self.anchor: dict = {}      # address -> first surface sample: the centre of a base-less planet's map
        self.visited: dict = {}     # address -> the mod's ua dict, for naming base-less planets
        self.timeline: list = []    # [(t, address)] at each change of planet, for placing visor finds
        self.by_centre: dict = {}   # rounded nearest-planet centre -> address, for samples that lack one
        self.charted: dict = {}     # address -> {fine cell path: [first t, last t]} (sectors.py)
        self._last = 0

    def refresh(self):
        """New trail rows from nms-db; their address was filled in at ingest (db.Ingest)."""
        self._last, rows = db.tail("trail", self._last)
        for address, s in rows:
            if address is None or not s.get("rel"):
                continue
            if s.get("planet_pos") and (address >> 52) & 0xF:
                self.by_centre[tuple(round(c) for c in s["planet_pos"])] = address
            self.add(address, s)

    def add(self, address, s):
        """One sample (from a trail line, or the latest live.json)."""
        if (not self.timeline or self.timeline[-1][1] != address) and s.get("t", 0) >= (self.timeline[-1][0] if self.timeline else 0):
            self.timeline.append((s["t"], address))
        rel = s["rel"]
        dfp = s.get("distance_from_planet")
        if dfp is not None and dfp < 20000 and (address >> 52) & 0xF:
            # 818 of 1,002 samples on Pondal IX gave 98304; a few (ship, underwater) gave 98280-98303,
            # so the most common value is the planet's, not the latest one
            c = self._radii.setdefault(address, Counter())
            c[round(math.hypot(*rel) - dfp)] += 1
            self.radius[address] = c.most_common(1)[0][0]
            self.anchor.setdefault(address, rel)
            self.visited.setdefault(address, s.get("ua"))
            if s.get("sealevel"):
                self.water[address] = s["sealevel"]
            if dfp < sectors.CHART_ALT_M:
                path = sectors.locate(rel)
                if path:
                    c = self.charted.setdefault(address, {}).get(path)
                    t = s.get("t", 0)
                    self.charted[address][path] = [min(c[0], t), max(c[1], t)] if c else [t, t]
        if s.get("location") in GROUND_LOCATIONS:
            self.samples.setdefault(address, []).append(rel)


def _mine(bases, address):
    return [b for b in bases if maps._addr(b.get("GalacticAddress")) == address and b.get("Position")
            and (b.get("BaseType") or {}).get("PersistentBaseTypes") not in maps.SKIP_BASES]


# Storm timing, seconds (gcskyglobals.globals, research/sources/game-data/25800958/
# gcskyglobals.globals.MXML.L68-92.xml), keyed by the planet's StormFrequency.
# Measured 2026-10-22 on an Extreme humid planet with StormFrequency Low: warning
# 25.0 s, build-up 20.1 s, storm 315.0 s, clearing 20.0 s. 315 s is outside the
# Low length (120-180) and inside High (150-320), so storm length excludes the
# transitions and an Extreme planet appears to use the High length. The next
# storm came 359 s after the first cleared, fitting the ExtremeFallback gap.
STORM_WARNING_S = 25
STORM_TRANSITION_S = 20
STORM_TIMING = {"Low": {"length": (120, 180), "between": (900, 2400)},
                "High": {"length": (150, 320), "between": (120, 620)},
                "Extreme": {"length": (150, 320), "between": (240, 620)}}
# Order of the six values in each cGcPlanetHazardData table (weather files, e.g. humidweather.MXML).
HAZARD_SLOTS = ("ambient", "water", "cave", "storm", "night", "deep_water")


def storm_eta(storm: dict | None, frequency: str | None, now: float, intensity: str | None = None) -> dict:
    """Where the storm cycle is and the time ranges ahead, from the last
    SetStormState transition and the game's storm timing for this planet."""
    if frequency == "Always":
        return {"note": "constant storms"}
    if frequency in (None, "None_"):
        return {"note": "no storms on this planet"} if frequency else {}
    if not storm:
        return {"note": "no storm change seen since the mod loaded"}
    t = STORM_TIMING.get("Extreme" if intensity == "Extreme" else frequency)
    el = now - storm["t"]
    rng = lambda lo, hi: [max(0, round(lo - el)), max(0, round(hi - el))]  # noqa: E731
    phase = storm["state"]
    if phase == "Warning":
        return {"phase": phase, "starts_in": max(0, round(STORM_WARNING_S - el))}
    if phase == "TransitionIn" and t:
        lo, hi = t["length"]
        return {"phase": phase, "ends_in": rng(lo + STORM_TRANSITION_S, hi + STORM_TRANSITION_S)}
    if phase == "Active" and t:
        return {"phase": phase, "ends_in": rng(*t["length"])}
    if phase == "TransitionOut":
        return {"phase": phase, "clears_in": max(0, round(STORM_TRANSITION_S - el))}
    if phase == "Inactive" and t:
        return {"phase": phase, "next_in": rng(*t["between"])}
    return {"phase": phase}


class Live:
    def projection(self, bases, address):
        """The planet map's projection: centred on the bases, or for a planet
        without bases on where the player first arrived (stable across visits)."""
        mine = _mine(bases, address)
        if mine:
            return maps.planet_projection(mine)
        if address in self.elev.anchor and address in self.elev.radius:
            return maps.Projection(self.elev.anchor[address], self.elev.radius[address])
        return None

    def visited_planets(self, bases) -> list:
        """/api/map entries for planets visited with the mod that have no bases."""
        self.elev.refresh()
        # only planetary bases: the corvette and freighter are bases too, at wherever they are now
        with_bases = {maps._addr(b.get("GalacticAddress")) for b in bases
                      if (b.get("BaseType") or {}).get("PersistentBaseTypes") not in maps.SKIP_BASES}
        out = []
        for address, ua in self.elev.visited.items():
            if address in with_bases or address not in self.elev.radius:
                continue
            ua = ua or {}
            self.systems.refresh()
            pname, sname = self.systems.planet_name(address), self.systems.system_name(address)
            out.append({"address": f"0x{address:X}", "radius": self.elev.radius[address],
                        "label": f"{pname or 'Planet ' + str(ua.get('planet', '?'))} in {sname or 'system ' + str(ua.get('system', '?'))} (no bases)",
                        "bases": [], "points": [], "layouts": {}, "visited": True})
        return out

    def __init__(self):
        self.trail = Trail()
        self.elev = Elevation()
        self.finds = Finds(LIVE_DIR)
        self.systems = Systems(LIVE_DIR)
        self._grid_key = None
        self._grid = None
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

    @staticmethod
    def weather(sample: dict, items: dict) -> dict | None:
        """The mod's weather block, with resource IDs named from the item table."""
        w = sample.get("weather")
        if not w:
            return None
        p = dict(w.get("planet") or {})
        if p.get("substances"):
            p["substances"] = [(items.get(i) or {}).get("name") or i for i in p["substances"] if i]
        if p.get("hazard"):
            p["hazard"] = {k: dict(zip(HAZARD_SLOTS, v)) for k, v in p["hazard"].items()}
        eta = storm_eta(w.get("storm"), p.get("storm_frequency"), sample.get("t", time.time()), p.get("intensity"))
        return {**w, "planet": p or None, "storm_eta": eta}

    def finds_api(self, bases: list, address: int | None, base: str | None, tables: dict) -> dict:
        """Hotspots and deposits on a planet, placed on its map (and a base layout)."""
        self.elev.refresh()
        self.finds.refresh(self.elev.timeline)
        proj = self.projection(bases, address) if address is not None else None
        if proj is None:
            return {"finds": []}
        frame = None
        if base:
            b = next((b for b in _mine(bases, address) if (b.get("Name") or "base") == base), None)
            frame = (b, *maps.base_en(b)) if b and maps.base_en(b) else None
        out = []
        for f in self.finds.for_planet(address, tables):
            x, y = proj.xy(f["w"])
            f.update(x=round(x, 1), y=round(y, 1))
            if frame:
                e, n, h = frame[2](maps.world_to_local(frame[0], frame[1], f["w"]))
                f.update(e=e, n=n, h=h)
            out.append(f)
        hs = (tables.get("extraction") or {}).get("hotspots") or {}
        ranges = {"hotspot-mineral": (hs.get("Mineral1") or {}).get("range_m"), "hotspot-gas": (hs.get("Gas1") or {}).get("range_m"),
                  "hotspot-power": (hs.get("Power") or {}).get("range_m")}
        return {"finds": out, "range_m": ranges["hotspot-mineral"], "ranges": ranges,
                "unmatched_labels": self.finds.chat_labels(address)[1]}

    def build(self, bases: list, base: str | None = None, target: str | None = None, trail_s: float = 6 * 3600,
              items: dict | None = None, tables: dict | None = None) -> dict:
        sample, err = read_sample()
        if sample is None:
            return {"state": "none", "error": err}
        age = time.time() - sample.get("t", 0)
        out = {"state": "stale" if age > STALE_S else "live", "age": round(age, 1),
               "location": sample.get("location"), "error": None, "weather": self.weather(sample, items or {})}
        # The position itself is a file; the trail, names and finds are in nms-db. With the
        # database down the position still shows and `db` says why the rest is missing.
        db_err = None if db.configured() else "nms-db not configured: no PGHOST"

        def guarded(fn, *a):
            nonlocal db_err
            if db_err:
                return None
            try:
                return fn(*a)
            except psycopg.Error as e:
                db_err = f"nms-db unreachable: {e}".strip()
                return None

        def finish(o):
            o["db"] = db_err is None
            if db_err:
                o["db_error"] = db_err
            return o

        address = ua_int(sample.get("ua"))
        if address is None and sample.get("planet_pos"):
            # no address yet (attached mid-game): the same planet centre was seen with one before
            guarded(self.elev.refresh)
            address = self.elev.by_centre.get(tuple(round(c) for c in sample["planet_pos"]))
            out["address_inferred"] = address is not None
        out["address"] = f"0x{address:X}" if address is not None else None
        guarded(self.systems.refresh)
        out["names"] = {"planet": self.systems.planet_name(address), "system": self.systems.system_name(address)}
        rel, at = sample.get("rel"), sample.get("at")
        planet_bases = [b for b in bases if b.get("Position")
                        and (b.get("BaseType") or {}).get("PersistentBaseTypes") not in maps.SKIP_BASES]
        mine = [b for b in planet_bases if maps._addr(b.get("GalacticAddress")) == address]
        # planet bits 0 = in the system but at no planet (space, galaxy map), whatever the distance says
        surface = (address is not None and (address >> 52) & 0xF != 0
                   and (sample.get("in_atmosphere") or sample.get("distance_from_planet", 1e9) <= 20000))
        if address is not None and rel and surface:
            guarded(self.elev.refresh)
            self.elev.add(address, sample)        # the first moments on a new planet may not be in the trail yet
            self.finds.remember_planet(address, (sample.get("weather") or {}).get("planet"))
        proj = self.projection(bases, address) if address is not None else None
        if address is None or proj is None or not rel or not at or not surface:
            out["on_planet"] = False
            # bases elsewhere in this star system (same address with the planet bits cleared)
            system = None if address is None else address & ~(0xF << 52)
            here = sorted({b.get("Name") or "base" for b in planet_bases
                           if system is not None and (maps._addr(b.get("GalacticAddress")) or 0) & ~(0xF << 52) == system})
            out["system_bases"] = here
            dfp = sample.get("distance_from_planet")
            if address is None:
                out["why"] = "waiting for the game to report where you are"
            elif not surface:
                out["why"] = (f"{dfp / 1000:.0f} km from the nearest planet" if dfp is not None else "in space") + (
                    f" · bases in this system: {', '.join(here)}" if here else " · no bases in this system")
            else:
                out["why"] = "on a planet with no bases" + (f" · bases in this system: {', '.join(here)}" if here else "")
            return finish(out)
        out["on_planet"] = True
        out["has_bases"] = bool(mine)
        up = _norm(rel)
        heading = heading_deg(up, at, sample.get("location"))
        x, y = proj.xy(rel)
        lat, lon = maps.latlon(rel)
        out["player"] = {"x": round(x, 1), "y": round(y, 1), "heading": None if heading is None else round(heading, 1),
                         "lat": lat, "lon": lon, "w": [round(c, 1) for c in rel]}

        guarded(self.trail.refresh)
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
        finds = [] if guarded(self.finds.refresh, self.elev.timeline) is None and db_err else self.finds.for_planet(address, tables or {})
        for f in finds:
            nv = nav(rel, heading, f["w"])
            label = f.get("resource") or f["name"]
            if f.get("class"):
                label = f"class {f['class']} · {label}"
            rows.append((nv["dist"], {"key": "w:" + ",".join(str(c) for c in f["w"]), "base": label or "",
                                      "kind": f["kind"], "id": f["name"], **nv}))
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
        return finish(out)

    def sectors(self, bases: list, address: int | None, tables: dict) -> dict:
        """The planet's 32 sectors and the cells the trail has charted (sectors.py), with
        flat-map coordinates for the cells and sector edges on this planet's projection."""
        self.elev.refresh()
        self.finds.refresh(self.elev.timeline)
        radius = self.elev.radius.get(address)
        if address is None or radius is None:
            return {"error": "not known until you visit this planet with the live_position mod running", "sectors": [], "cells": []}
        places = [("base", b.get("Name") or "base", b["Position"][:3]) for b in _mine(bases, address)]
        places += [(f["kind"], f.get("name"), f["w"]) for f in self.finds.for_planet(address, tables)]
        sample, _ = read_sample()
        here = sample["rel"] if sample and ua_int(sample.get("ua")) == address and sample.get("rel") else None
        out = sectors.describe(radius, self.elev.charted.get(address, {}), places, here)
        proj = self.projection(bases, address)
        if proj:
            xy = lambda u: [round(v, 1) for v in proj.xy([c * radius for c in u])]  # noqa: E731
            for c in out["cells"]:
                c["xy"] = [xy(u) for u in c["corners"]]
            for sec in out["sectors"]:
                # edges as polylines, sampled along the great circles; far side of the planet left out
                pts = []
                cs = sec["corners"]
                for a, b in zip(cs, cs[1:] + cs[:1]):
                    for k in range(17):
                        u = maps._norm([a[i] * (16 - k) / 16 + b[i] * k / 16 for i in range(3)])
                        pts.append(xy(u) if maps._dot(u, proj.c) > 0 else None)
                sec["edge_xy"] = pts
                sec["centre_xy"] = xy(sec["centre"]) if maps._dot(sec["centre"], proj.c) > 0 else None
        out["error"] = None
        return out

    def elevation(self, bases: list, address: int | None, base: str | None = None, cell: float = 25.0) -> dict:
        """Ground height above sea level in square cells of `cell` metres, on the
        planet projection or (with `base`) the base's layout frame."""
        self.elev.refresh()
        mine = _mine(bases, address)
        radius = self.elev.radius.get(address)
        if radius is None:
            return {"error": "not known until you visit this planet with the live_position mod running",
                    "cells": []}
        trail = self.elev.samples.get(address, [])
        water = self.elev.water.get(address)
        key = (address, base, cell, len(trail), id(bases), water)
        if key == self._grid_key:
            return self._grid
        if base:
            b = next((b for b in mine if (b.get("Name") or "base") == base), None)
            frame = maps.base_en(b) if b else None
            if not frame:
                return {"error": f"no layout for {base}", "cells": []}
            to_xy = lambda w: frame[1](maps.world_to_local(b, frame[0], w))[:2]  # noqa: E731
        else:
            to_xy = self.projection(bases, address).xy
        objs = [o[4] for o in self._objects(bases).get(address, []) if o[2] in GROUND_KINDS]
        grid: dict = {}
        for w in list(trail) + objs:
            x, y = to_xy(w)
            k = (math.floor(x / cell), math.floor(y / cell))
            h = math.hypot(*w) - radius
            if k not in grid or h < grid[k]:
                grid[k] = h
        # heights are from the water surface when the planet has one, else from the nominal radius
        ref = water or 0.0
        grid = {k: h - ref for k, h in grid.items()}
        hs = list(grid.values())
        out = {"cell": cell, "radius": radius, "water": water, "samples": len(trail), "objects": len(objs),
               "min": round(min(hs), 1) if hs else None, "max": round(max(hs), 1) if hs else None,
               "cells": [[i, j, round(h, 1)] for (i, j), h in grid.items()], "error": None}
        self._grid_key, self._grid = key, out
        return out
