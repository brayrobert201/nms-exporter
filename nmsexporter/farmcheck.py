"""Extractor hook-up checks shared by scripts/nms-farm-check and the /map page.

check_base(base) -> one row per extractor with its problems: not piped, no
depot, no wire, never filled. Networks come from pipe geometry alone. Fill
levels say nothing about connection within one save: units on one network gain
in lockstep but keep the offsets they started with, so a working network shows
many different fills (verified 2026-10-22 on Cobalt Oxygen across two saves).
A former "split off" check that read differing fills as disconnection was wrong
and is removed. Power is not traced to a generator: on working
farms the saved wires stop 4-15 m short of the generators (power passes through
parts or snap points the save does not describe). See the script's docstring.
Standard library only.
"""
from __future__ import annotations

import math

EXTRACTORS = {"^U_EXTRACTOR_S": "mineral", "^U_GASEXTRACTOR": "gas"}
DEPOT = "^U_SILO_S"
UNITS_PER_ITEM = 1440
PIPE_TOL = 3.2              # the game joins within 3; same tolerance as the exporter
WIRE_TOL = 2.5              # wire ends sit 0.2-2.2 from the part they feed (measured)


def fill(o) -> int:
    return o.get("UserData", 0) >> 32


def ends(seg) -> list:
    a = seg["Position"]
    return [a, [a[k] + seg["At"][k] for k in range(3)]]


class Graph:
    def __init__(self):
        self.parent = {}

    def find(self, x):
        while self.parent.setdefault(x, x) != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a, b):
        self.parent[self.find(a)] = self.find(b)


def trace(nodes: list, segs: list, tol: float) -> Graph:
    """Union nodes (indexes into nodes) and segments whose ends come within tol."""
    g = Graph()
    pts = [(i, e) for i, s in enumerate(segs) for e in ends(s)]
    for i, e in pts:
        g.find(("s", i))
        for j, n in enumerate(nodes):
            if math.dist(e, n["Position"]) < tol:
                g.union(("s", i), ("n", j))
        for i2, e2 in pts:
            if i2 != i and math.dist(e, e2) < tol:
                g.union(("s", i), ("s", i2))
    return g


def nearest_end(p, segs) -> float | None:
    ds = [math.dist(p, e) for s in segs for e in ends(s)]
    return min(ds) if ds else None


def check_base(b: dict) -> list:
    objs = b.get("Objects", [])
    exts = [o for o in objs if o["ObjectID"] in EXTRACTORS]
    if not exts:
        return []
    computer = next((o for o in objs if o["ObjectID"] == "^BASE_FLAG"), None)
    origin = computer["Position"] if computer else [0.0, 0.0, 0.0]
    pipes = [o for o in objs if o["ObjectID"] == "^U_PIPELINE"]
    wires = [o for o in objs if o["ObjectID"] == "^U_POWERLINE"]

    res = [o for o in objs if o["ObjectID"] in EXTRACTORS or o["ObjectID"] == DEPOT]
    pg = trace(res, pipes, PIPE_TOL)
    pipe_comp = {}
    for j, o in enumerate(res):
        pipe_comp.setdefault(pg.find(("n", j)), []).append(o)
    piped = {id(o) for j, o in enumerate(res)
             if any(pg.find(("s", i)) == pg.find(("n", j)) for i in range(len(pipes)))}

    wired = {id(o) for o in exts
             if any(math.dist(e, o["Position"]) < WIRE_TOL for w in wires for e in ends(w))}

    networks = [[o for o in c if o["ObjectID"] in EXTRACTORS] for c in pipe_comp.values()]
    networks = [n for n in networks if len(n) > 1]

    def nearest_network(o):
        best = None
        for n in networks:
            if any(x is o for x in n):
                continue
            d = min(math.dist(o["Position"], x["Position"]) for x in n)
            if best is None or d < best[0]:
                best = (d, EXTRACTORS[n[0]["ObjectID"]], len(n))
        return best

    rows = []
    for comp in pipe_comp.values():
        cexts = [o for o in comp if o["ObjectID"] in EXTRACTORS]
        has_depot = any(o["ObjectID"] == DEPOT for o in comp)
        for o in cexts:
            problems = []
            if id(o) not in piped:
                problems.append("not piped")
            elif not has_depot:
                problems.append("no depot")
            if id(o) not in wired:
                problems.append("no wire")
            if fill(o) == 0:
                problems.append("never filled")
            rel = [o["Position"][k] - origin[k] for k in range(3)]
            gap_p = nearest_end(o["Position"], pipes)
            gap_w = nearest_end(o["Position"], wires)
            rows.append({
                "kind": EXTRACTORS[o["ObjectID"]], "problems": problems,
                "network_size": len(cexts), "fill_items": fill(o) // UNITS_PER_ITEM,
                "from_computer_m": round(math.hypot(rel[0], rel[2])), "height_m": round(rel[1]),
                "x": round(rel[0]), "z": round(rel[2]),
                "pipe_gap_m": None if gap_p is None else round(gap_p, 1),
                "wire_gap_m": None if gap_w is None else round(gap_w, 1),
                "nearest_network": nearest_network(o) if problems else None,
                "pos": o["Position"],
            })
    return sorted(rows, key=lambda r: (not r["problems"], r["kind"], r["from_computer_m"]))
