"""Map data for the /map page: planets with their bases and points, and each
base's layout, all in metres east/north on a flat projection.

Frames (see knowledge/mechanics/save-coordinates.md):
- A planetary base's Position, exocraft and drained-deposit positions are
  measured from the planet centre. Points within 3% of the planet's radius
  (taken from its bases) are placed; anything else is a different frame.
- Base objects are in the base's own frame: x -> Right, y -> Up, z -> Forward,
  with Up = the base position normalised, Forward = the base's Forward made
  orthogonal, Right = Up x Forward (the rotation the exporter verified on
  refiners).
- North is the planet's +Y axis and east = north x up, checked against the
  in-game compass (research/sources/measurements/2026-10-22-live-position-compass.md).

Planet view: azimuthal equidistant projection centred on the planet's bases,
so distances and bearings from the centre are true. Base view: top-down, metres
from the base computer, rotated so north is up.

Standard library only.
"""
from __future__ import annotations

import math

from .farmcheck import EXTRACTORS, check_base

NORTH_AXIS = (0.0, 1.0, 0.0)
SKIP_BASES = {"FreighterBase", "PlayerShipBase", "PlayerSpaceBase"}
EXOCRAFT = ["Roamer", "Nomad", "Colossus", "Pilgrim", "Exocraft 5", "Nautilon", "Minotaur", "Exocraft 8"]


def _norm(v):
    n = math.sqrt(sum(x * x for x in v))
    return [x / n for x in v] if n else None


def _dot(a, b):
    return sum(x * y for x, y in zip(a, b))


def _cross(a, b):
    return [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]]


def _addr(a) -> int | None:
    try:
        return int(a, 16) if isinstance(a, str) else int(a)
    except (TypeError, ValueError):
        return None


def tangent_frame(up):
    """(north, east) unit vectors tangent to the sphere at unit vector up."""
    d = _dot(NORTH_AXIS, up)
    north = _norm([NORTH_AXIS[i] - d * up[i] for i in range(3)]) or [1.0, 0.0, 0.0]
    east = _norm(_cross(north, up))
    return north, east


def base_axes(b):
    up = _norm(b.get("Position") or [0, 0, 0])
    fwd = b.get("Forward") or [0, 0, 1]
    if not up:
        return None
    d = _dot(fwd, up)
    f = _norm([fwd[i] - d * up[i] for i in range(3)])
    if not f:
        return None
    return _cross(up, f), up, f            # right, up, forward


def local_to_world(b, axes, p):
    r, u, f = axes
    return [b["Position"][i] + r[i] * p[0] + u[i] * p[1] + f[i] * p[2] for i in range(3)]


def latlon(p):
    u = _norm(p)
    lat = math.degrees(math.asin(max(-1.0, min(1.0, u[1]))))
    lon = math.degrees(math.atan2(u[0], u[2]))
    return round(lat, 4), round(lon, 4)


class Projection:
    """Azimuthal equidistant about a centre direction, in metres."""

    def __init__(self, centre, radius):
        self.c = _norm(centre)
        self.r = radius
        self.north, self.east = tangent_frame(self.c)

    def xy(self, p):
        u = _norm(p)
        cosang = max(-1.0, min(1.0, _dot(u, self.c)))
        ang = math.acos(cosang)
        if ang < 1e-9:
            return 0.0, 0.0
        t = _norm([u[i] - cosang * self.c[i] for i in range(3)])
        dist = self.r * ang
        return dist * _dot(t, self.east), dist * _dot(t, self.north)


def _kind(oid: str) -> str:
    if oid in EXTRACTORS:
        return "extractor-" + EXTRACTORS[oid]
    if oid == "^U_SILO_S":
        return "depot"
    if oid in ("^U_GENERATOR_S", "^U_BIOGENERATOR", "^U_SOLAR_S", "^U_BATTERY_S"):
        return "power"
    if "REFINER" in oid:
        return "refiner"
    if oid in ("^TELEPORTER", "^U_MINIPORTAL"):
        return "teleporter"
    if oid == "^BASE_FLAG":
        return "computer"
    if "PLANTER" in oid or oid.startswith("^PLANT") or "BIOROOM" in oid:
        return "plants"
    return "structure"


SEGMENTS = {"^U_PIPELINE": "pipe", "^U_POWERLINE": "wire", "^U_PORTALLINE": "link"}


def base_layout(b) -> dict | None:
    axes = base_axes(b)
    if not axes:
        return None
    r, up, f = axes
    north, east = tangent_frame(up)
    # local (x, z) -> (east, north): project the base's Right and Forward axes
    rx, rz = _dot(r, east), _dot(f, east)
    nx, nz = _dot(r, north), _dot(f, north)
    objs = b.get("Objects") or []
    comp = next((o for o in objs if o.get("ObjectID") == "^BASE_FLAG"), None)
    o0 = comp["Position"] if comp else [0.0, 0.0, 0.0]

    def en(p):
        x, z = p[0] - o0[0], p[2] - o0[2]
        return round(rx * x + rz * z, 2), round(nx * x + nz * z, 2), round(p[1] - o0[1], 1)

    flags = {}
    for row in check_base(b):
        if row["problems"]:
            flags[tuple(row["pos"])] = row
    items, segs = [], []
    for o in objs:
        oid = o.get("ObjectID") or ""
        p = o.get("Position")
        if not p:
            continue
        if oid in SEGMENTS:
            q = [p[i] + o["At"][i] for i in range(3)]
            a, c = en(p), en(q)
            segs.append({"kind": SEGMENTS[oid], "a": a[:2], "b": c[:2]})
            continue
        e, n, h = en(p)
        item = {"kind": _kind(oid), "id": oid.lstrip("^"), "e": e, "n": n, "h": h}
        row = flags.get(tuple(p))
        if row:
            item["problems"] = row["problems"]
            item["fill"] = row["fill_items"]
            item["pipe_gap"] = row["pipe_gap_m"]
            nn = row.get("nearest_network")
            if nn:
                item["near"] = f"{nn[0]:.0f} m from a {nn[1]} network of {nn[2]}"
        items.append(item)
    return {"items": items, "segments": segs, "loose": sum(1 for i in items if i.get("problems"))}


def build(ps_points: dict, bases: list) -> dict:
    """ps_points: the save fields kept by the collector (vehicles, deposits,
    settlements). bases: collector.raw_bases."""
    planets: dict = {}
    for b in bases:
        t = (b.get("BaseType") or {}).get("PersistentBaseTypes")
        if t in SKIP_BASES or not b.get("Position"):
            continue
        key = _addr(b.get("GalacticAddress"))
        planets.setdefault(key, []).append(b)

    out = []
    for key, bs in planets.items():
        radius = sum(math.hypot(*b["Position"][:3]) for b in bs) / len(bs)
        centre = [sum(b["Position"][i] for b in bs) for i in range(3)]
        proj = Projection(centre, radius)
        pts, layouts = [], {}
        for b in bs:
            x, y = proj.xy(b["Position"])
            name = b.get("Name") or "base"
            lay = base_layout(b)
            layouts[name] = lay
            lat, lon = latlon(b["Position"])
            pts.append({"kind": "base", "name": name, "x": round(x, 1), "y": round(y, 1),
                        "lat": lat, "lon": lon, "loose": (lay or {}).get("loose", 0),
                        "objects": len(b.get("Objects") or [])})

        def near_planet(p):
            return p and abs(math.hypot(*p[:3]) - radius) < 0.03 * radius

        for i, v in enumerate(ps_points.get("vehicles", [])):
            if _addr(v.get("Location")) == key and near_planet(v.get("Position")):
                x, y = proj.xy(v["Position"])
                pts.append({"kind": "exocraft", "name": EXOCRAFT[i] if i < len(EXOCRAFT) else f"Exocraft {i + 1}",
                            "x": round(x, 1), "y": round(y, 1)})
        for d in ps_points.get("deposits", []):
            if _addr(d.get("GalacticAddress")) == key and near_planet(d.get("Position")):
                x, y = proj.xy(d["Position"])
                pts.append({"kind": "deposit", "name": "Drained deposit", "x": round(x, 1), "y": round(y, 1)})
        for s in ps_points.get("settlements", []):
            if _addr(s.get("UniverseAddress")) == key and near_planet(s.get("Position")):
                x, y = proj.xy(s["Position"])
                pts.append({"kind": "settlement", "name": s.get("Name") or "Settlement",
                            "x": round(x, 1), "y": round(y, 1)})
        names = sorted(b.get("Name") or "base" for b in bs)
        out.append({"address": f"0x{key:X}" if key is not None else "?", "radius": round(radius),
                    "label": names[0] if len(names) == 1 else f"{names[0]} + {len(names) - 1} more",
                    "bases": names, "points": pts, "layouts": layouts})
    out.sort(key=lambda p: -len(p["bases"]))
    return {"north_verified": True, "planets": out}
