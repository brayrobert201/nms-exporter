"""Star systems and names seen in game, from pymhf_mods/galaxy_log.py's
systems-YYYYMMDD.jsonl.

- A system record (economy, wealth, conflict, race, star, planets, planet
  seeds, flags) is keyed by its universe address with the planet bits clear.
- A system name's seed is that address; a planet name's seed is one of the
  system's PlanetSeeds. Planet address bits n (1-based) are taken to name
  PlanetSeeds[n - 1]: seen once (Activated Indium's planet, address planet 1,
  was named from seed 0 while the player was there).
- Distance: galactic voxels are taken as 400 light years (the usual rule; not
  in the game's data), so systems in one voxel show as the same region.

Standard library only; reads never raise.
"""
from __future__ import annotations

import glob
import json
import math
import os

LY_PER_VOXEL = 400
SKIP_BASES = {"FreighterBase", "PlayerShipBase", "PlayerSpaceBase"}   # as maps.SKIP_BASES
PLANET_BITS = 0xF << 52


def system_ua(address: int) -> int:
    return address & ~PLANET_BITS


def voxel(address: int) -> tuple:
    def signed(v, bits):
        return v - (1 << bits) if v >= 1 << (bits - 1) else v
    return (signed(address & 0xFFF, 12), signed((address >> 24) & 0xFF, 8), signed((address >> 12) & 0xFFF, 12))


class Systems:
    def __init__(self, live_dir: str):
        self.dir = live_dir
        self._pos: dict = {}
        self.systems: dict = {}       # system UA -> record
        self.names: dict = {}         # system UA -> name
        self.planet_names: dict = {}  # planet seed -> name

    def refresh(self):
        for path in sorted(glob.glob(os.path.join(self.dir, "systems-*.jsonl"))):
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
                    r = json.loads(line)
                except ValueError:
                    continue
                ev = r.get("event")
                if ev == "system" and r.get("ua") is not None:
                    self.systems[system_ua(r["ua"])] = r
                elif ev == "system_name" and r.get("name"):
                    self.names[system_ua(r["seed"])] = r["name"]
                elif ev == "planet_name" and r.get("name"):
                    self.planet_names[r["seed"]] = r["name"]

    def system_name(self, address: int | None) -> str | None:
        return None if address is None else self.names.get(system_ua(address))

    def planet_name(self, address: int | None) -> str | None:
        if address is None:
            return None
        rec = self.systems.get(system_ua(address))
        n = (address >> 52) & 0xF
        seeds = (rec or {}).get("planet_seeds") or []
        return self.planet_names.get(seeds[n - 1]) if 1 <= n <= len(seeds) else None

    def listing(self, here: int | None, bases: list) -> list:
        """Every system seen, with distance from `here` (any address in the player's system)."""
        base_systems: dict = {}
        for b in bases:
            if (b.get("BaseType") or {}).get("PersistentBaseTypes") in SKIP_BASES:
                continue
            ga = b.get("GalacticAddress")
            try:
                a = int(ga, 16) if isinstance(ga, str) else int(ga)
            except (TypeError, ValueError):
                continue
            base_systems.setdefault(system_ua(a), set()).add(b.get("Name") or "base")
        hv = voxel(here) if here is not None else None
        out = []
        for ua, r in self.systems.items():
            v = voxel(ua)
            d = math.dist(v, hv) * LY_PER_VOXEL if hv else None
            out.append({"ua": f"0x{ua:X}", "name": self.names.get(ua), "economy": r.get("economy"),
                        "wealth": r.get("wealth"), "conflict": r.get("conflict"), "race": r.get("race"),
                        "star": r.get("star"), "anomaly": r.get("anomaly"), "planets": r.get("planets"),
                        "planet_names": [self.planet_names.get(s) for s in r.get("planet_seeds") or []],
                        "pirate": r.get("pirate"), "abandoned": r.get("abandoned"),
                        "here": here is not None and system_ua(here) == ua,
                        "distance_ly": None if d is None else round(d), "voxel": list(v),
                        "bases": sorted(base_systems.get(ua, ()))})
        out.sort(key=lambda s: (s["distance_ly"] is None, s["distance_ly"] or 0, s["name"] or ""))
        return out
