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

import glob
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
        self.radius: dict = {}      # address -> nominal radius
        self.water: dict = {}       # address -> water surface above the nominal radius (absent: no sea seen)
        self.anchor: dict = {}      # address -> first surface sample: the centre of a base-less planet's map
        self.visited: dict = {}     # address -> the mod's ua dict, for naming base-less planets
        self._pos: dict = {}

    def refresh(self):
        for path in sorted(glob.glob(os.path.join(LIVE_DIR, "trail-*.jsonl"))):
            try:
                with open(path, "rb") as f:
                    f.seek(self._pos.get(path, 0))
                    data = f.read()
            except OSError:
                continue
            end = data.rfind(b"\n") + 1
            self._pos[path] = self._pos.get(path, 0) + end
            for line in data[:end].splitlines():
                try:
                    s = json.loads(line)
                    address, rel = ua_int(s.get("ua")), s["rel"]
                except (ValueError, KeyError, TypeError):
                    continue
                if address is None:
                    continue
                self.add(address, s)

    def add(self, address, s):
        """One sample (from a trail line, or the latest live.json)."""
        rel = s["rel"]
        dfp = s.get("distance_from_planet")
        if dfp is not None and dfp < 20000:
            self.radius[address] = round(math.hypot(*rel) - dfp)
            self.anchor.setdefault(address, rel)
            self.visited.setdefault(address, s.get("ua"))
            if s.get("sealevel"):
                self.water[address] = s["sealevel"]
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
# transitions and an Extreme planet appears to use the High length; its gap is
# taken as ExtremeFallback (240-620 s) until the next storm confirms it.
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
        with_bases = {maps._addr(b.get("GalacticAddress")) for b in bases}
        out = []
        for address, ua in self.elev.visited.items():
            if address in with_bases or address not in self.elev.radius:
                continue
            ua = ua or {}
            out.append({"address": f"0x{address:X}", "radius": self.elev.radius[address],
                        "label": f"Planet {ua.get('planet', '?')} of system {ua.get('system', '?')} (no bases)",
                        "bases": [], "points": [], "layouts": {}, "visited": True})
        return out

    def __init__(self):
        self.trail = Trail()
        self.elev = Elevation()
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

    def build(self, bases: list, base: str | None = None, target: str | None = None, trail_s: float = 6 * 3600,
              items: dict | None = None) -> dict:
        sample, err = read_sample()
        if sample is None:
            return {"state": "none", "error": err}
        age = time.time() - sample.get("t", 0)
        out = {"state": "stale" if age > STALE_S else "live", "age": round(age, 1),
               "location": sample.get("location"), "error": None, "weather": self.weather(sample, items or {})}
        address = ua_int(sample.get("ua"))
        out["address"] = f"0x{address:X}" if address is not None else None
        rel, at = sample.get("rel"), sample.get("at")
        planet_bases = [b for b in bases if b.get("Position")
                        and (b.get("BaseType") or {}).get("PersistentBaseTypes") not in maps.SKIP_BASES]
        mine = [b for b in planet_bases if maps._addr(b.get("GalacticAddress")) == address]
        surface = sample.get("in_atmosphere") or sample.get("distance_from_planet", 1e9) <= 20000
        if address is not None and rel and surface:
            self.elev.refresh()
            self.elev.add(address, sample)        # the first moments on a new planet may not be in the trail yet
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
            return out
        out["on_planet"] = True
        out["has_bases"] = bool(mine)
        up = _norm(rel)
        heading = heading_deg(up, at)
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
