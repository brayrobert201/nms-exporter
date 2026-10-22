"""Planet sectors for the /map "charted" layer: 8 octants, each cut into 4.

The idea comes from players asking for a planet map that fills in as you
explore. Each octant (the planet's
frame split by the signs of x, y, z; north is +Y) is a spherical triangle with
one corner at a pole and two on the equator. Joining its edge midpoints splits
it into 4: the polar corner (P), the west and east equatorial corners (W, E,
by longitude) and the centre (C). That gives 32 sectors, named e.g. "N1 polar"
(N/S hemisphere, quadrant 1-4 = longitude 0-90°E, 90-180°E, 90-180°W, 0-90°W;
longitude as maps.latlon, east positive).

The same midpoint split, repeated, gives cells within a sector. A cell is
"charted" when the trail has been in it (on foot, in an exocraft or flying
below CHART_ALT_M). Cells are stored as paths at FINE_DEPTH and grouped to a
display depth chosen from the planet's radius, so a cell is about CELL_M
across on any planet.

Standard library only.
"""
from __future__ import annotations

import math

FINE_DEPTH = 8          # 4^8 = 65,536 cells per sector; 0.3 km on a 98 km planet
CELL_M = 1000.0         # target display cell size
CHART_ALT_M = 2000.0    # trail samples higher than this are not charting the ground

QUADRANTS = ["0–90°E", "90–180°E", "90–180°W", "0–90°W"]
PARTS = ["polar", "west", "east", "centre"]   # child order of split(): corner a, b, c, then the middle


def _norm(v):
    n = math.sqrt(v[0] * v[0] + v[1] * v[1] + v[2] * v[2])
    return (v[0] / n, v[1] / n, v[2] / n) if n else None


def _det(a, b, c):
    return (a[0] * (b[1] * c[2] - b[2] * c[1]) - a[1] * (b[0] * c[2] - b[2] * c[0])
            + a[2] * (b[0] * c[1] - b[1] * c[0]))


def octant(i: int):
    """Octant i (0-7: N1..N4, S1..S4) as (pole, west corner, east corner)."""
    pole = (0.0, 1.0 if i < 4 else -1.0, 0.0)
    eq = [(0.0, 0.0, 1.0), (1.0, 0.0, 0.0), (0.0, 0.0, -1.0), (-1.0, 0.0, 0.0)]   # longitude 0, 90E, 180, 90W
    q = i % 4
    return pole, eq[q], eq[(q + 1) % 4]


def split(t):
    a, b, c = t
    ab, bc, ca = (_norm([x + y for x, y in zip(p, q)]) for p, q in ((a, b), (b, c), (c, a)))
    return [(a, ab, ca), (ab, b, bc), (ca, bc, c), (ab, bc, ca)]


def _inside(t, u) -> float:
    """> 0 inside triangle t, the smallest margin to an edge (signed)."""
    s = 1.0 if _det(*t) > 0 else -1.0
    return min(s * _det(t[0], t[1], u), s * _det(t[1], t[2], u), s * _det(t[2], t[0], u))


def octant_of(u) -> int:
    lon = math.degrees(math.atan2(u[0], u[2])) % 360.0    # 0..360 east
    q = 0 if lon < 90 else 1 if lon < 180 else 3 if lon >= 270 else 2
    return q + (0 if u[1] >= 0 else 4)


def locate(rel, depth: int = FINE_DEPTH) -> str | None:
    """Cell path of a planet-frame position: octant digit then one digit (0-3) per split."""
    u = _norm(rel)
    if u is None:
        return None
    o = octant_of(u)
    t, path = octant(o), [str(o)]
    for _ in range(depth):
        kids = split(t)
        k = max(range(4), key=lambda i: _inside(kids[i], u))
        t = kids[k]
        path.append(str(k))
    return "".join(path)


def triangle(path: str):
    t = octant(int(path[0]))
    for d in path[1:]:
        t = split(t)[int(d)]
    return t


def sector_id(path: str) -> str:
    o, part = int(path[0]), int(path[1])
    return f"{'N' if o < 4 else 'S'}{o % 4 + 1}{'PWEC'[part]}"


def sector_name(path: str) -> str:
    o, part = int(path[0]), int(path[1])
    return f"{'N' if o < 4 else 'S'}{o % 4 + 1} {PARTS[part]}"


def display_depth(radius: float) -> int:
    """Splits below sector level that make a cell about CELL_M across."""
    edge = radius * math.pi / 4                      # a sector's edge, roughly
    return max(1, min(FINE_DEPTH - 1, round(math.log2(max(edge / CELL_M, 1.0)))))


def all_sectors():
    for o in range(8):
        for part in range(4):
            yield f"{o}{part}"


def describe(radius: float, charted: dict, places: list, here=None) -> dict:
    """charted: fine path -> [first, last] seen. places: [(kind, name, rel)] to count per sector.
    here: the player's rel, or None."""
    depth = display_depth(radius)
    per = 4 ** depth
    cells: dict = {}
    for path, (first, last) in charted.items():
        key = path[:2 + depth]
        c = cells.get(key)
        cells[key] = [min(first, c[0]), max(last, c[1])] if c else [first, last]
    counts: dict = {}
    for kind, name, rel in places:
        p = locate(rel, 1)
        if p:
            counts.setdefault(p, []).append((kind, name))
    sectors = []
    for s in all_sectors():
        mine = [v for k, v in cells.items() if k.startswith(s)]
        t = triangle(s)
        centre = _norm([sum(c[i] for c in t) for i in range(3)])
        here_ = counts.get(s, [])
        sectors.append({"id": sector_id(s), "name": sector_name(s), "path": s, "quadrant": QUADRANTS[int(s[0]) % 4],
                        "corners": [[round(x, 5) for x in c] for c in t], "centre": [round(x, 5) for x in centre],
                        "charted": len(mine), "pct": round(100 * len(mine) / per, 3),
                        "first": min((v[0] for v in mine), default=None), "last": max((v[1] for v in mine), default=None),
                        "bases": sorted(n for k, n in here_ if k == "base"), "finds": sum(1 for k, _ in here_ if k != "base")})
    edge = radius * math.pi / 4 / 2 ** depth
    you = locate(here, 1) if here else None
    return {"radius": radius, "depth": depth, "cells_per_sector": per, "cell_km": round(edge / 1000, 2),
            "sectors": sectors, "you": sector_id(you) if you else None,
            "total": {"charted": len(cells), "cells": per * 32, "pct": round(100 * len(cells) / (per * 32), 4)},
            "cells": [{"sector": sector_id(k), "corners": [[round(x, 5) for x in c] for c in triangle(k)],
                       "first": v[0], "last": v[1]} for k, v in sorted(cells.items())]}
