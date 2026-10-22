"""Hotspots and resource deposits found in game, for the /map "finds" layer.

Source: pymhf_mods/visor_log.py's visor-YYYYMMDD.jsonl. The game adds a
MineralHotspot / GasHotspot / PowerHotspot marker when the player reaches the
point the survey led to, and TerrainResource markers ("Cobalt Deposit") as an
area loads. Marker local + offset - nearest planet centre is the planet frame
(a PlayerBase marker sat 4.6 m above its base's saved Position). A marker row
has no address, so it is placed on the planet the trail says the player was on
at that time.

Which substance a hotspot gives is not in the marker:
- deposit: its own name ("Cobalt Deposit" -> Cobalt);
- gas: Gas1 is set by the planet's biome (REGIONHOTSPOTSTABLE, data/nms_tables.json
  extraction.biome_gases), Gas2 is always Oxygen;
- mineral: the table has Mineral1-3. Assumed Mineral1 = the planet's common
  substance, from one planet where the farm on the hotspot extracts the common
  one (Activated Indium); uncommon and rare are given as the alternatives.
The class (C/B/A/S) is not in the marker's mapped fields. Until its byte is
found the player records it from the visor (POST /api/finds/class), kept in
LIVE_DIR/find_labels.json; each labelled hotspot with a raw struct is also an
example for finding the byte.

Planet facts (biome, substances) come from live.json's weather block and are
kept in LIVE_DIR/planets.json so they outlive both the visit and an exporter
restart. Standard library only; reads never raise.
"""
from __future__ import annotations

import bisect
import glob
import json
import os

TYPES = {"MineralHotspot": "hotspot-mineral", "GasHotspot": "hotspot-gas", "PowerHotspot": "hotspot-power",
         "TerrainResource": "deposit"}
MERGE_M = 5.0


class Finds:
    def __init__(self, live_dir: str):
        self.dir = live_dir
        self._pos: dict = {}
        self.rows: dict = {}          # (address, kind, rounded position) -> find
        self._pending: list = []      # marker rows seen before the trail covered their time
        self.planets: dict = {}       # address (int) -> planet facts
        self.labels: dict = {}        # find key -> {"class": "B"}
        try:
            with open(os.path.join(live_dir, "find_labels.json")) as f:
                self.labels = json.load(f)
        except (OSError, ValueError):
            pass
        try:
            with open(os.path.join(live_dir, "planets.json")) as f:
                self.planets = {int(k): v for k, v in json.load(f).items()}
        except (OSError, ValueError):
            pass

    def remember_planet(self, address: int | None, planet: dict | None):
        if address is None or not planet or not planet.get("substances"):
            return
        keep = {k: planet.get(k) for k in ("substances", "biome", "weather", "storm_frequency", "intensity")}
        if self.planets.get(address) == keep:
            return
        self.planets[address] = keep
        try:
            tmp = os.path.join(self.dir, "planets.json.tmp")
            with open(tmp, "w") as f:
                json.dump({str(k): v for k, v in self.planets.items()}, f)
            os.replace(tmp, os.path.join(self.dir, "planets.json"))
        except OSError:
            pass

    def refresh(self, timeline: list):
        """timeline: sorted [(t, address)] of planet changes from the trail."""
        new = self._pending
        self._pending = []
        for path in sorted(glob.glob(os.path.join(self.dir, "visor-*.jsonl"))):
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
                if r.get("event") == "marker_add" and r.get("type") in TYPES and r.get("rel"):
                    new.append(r)
        times = [t for t, _ in timeline]
        for r in new:
            i = bisect.bisect_right(times, r["t"]) - 1
            if i < 0:
                self._pending.append(r)
                continue
            address = timeline[i][1]
            kind = TYPES[r["type"]]
            key = (address, kind) + tuple(round(c / MERGE_M) for c in r["rel"])
            f = self.rows.get(key)
            if f is None:
                self.rows[key] = {"kind": kind, "name": r.get("name"), "w": r["rel"], "address": address,
                                  "first": r["t"], "last": r["t"], "raw": r.get("raw")}
            else:
                f["last"] = max(f["last"], r["t"])
                f["raw"] = f["raw"] or r.get("raw")

    @staticmethod
    def key(f: dict) -> str:
        return f"{f['address']:X}:{f['kind']}:" + ":".join(str(round(c / MERGE_M)) for c in f["w"])

    def set_class(self, key: str, cls: str | None) -> bool:
        if cls not in (None, "C", "B", "A", "S") or not any(self.key(f) == key for f in self.rows.values()):
            return False
        if cls:
            self.labels[key] = {"class": cls, "t": round(__import__("time").time())}
        else:
            self.labels.pop(key, None)
        try:
            tmp = os.path.join(self.dir, "find_labels.json.tmp")
            with open(tmp, "w") as fh:
                json.dump(self.labels, fh)
            os.replace(tmp, os.path.join(self.dir, "find_labels.json"))
        except OSError:
            return False
        return True

    def resource(self, f: dict, tables: dict) -> dict:
        items = tables.get("items") or {}
        name = lambda i: (items.get(i) or {}).get("name") or i  # noqa: E731
        planet = self.planets.get(f["address"]) or {}
        subs = planet.get("substances") or []
        if f["kind"] == "deposit":
            return {"resource": (f["name"] or "").replace(" Deposit", "") or None, "basis": "the deposit's name"}
        if f["kind"] == "hotspot-power":
            return {"resource": "Power", "basis": "hotspot type"}
        if f["kind"] == "hotspot-gas":
            gases = ((tables.get("extraction") or {}).get("biome_gases") or {}).get(planet.get("biome") or "")
            if not gases:
                return {"resource": None, "basis": "planet biome not known yet"}
            g1, g2 = name(gases["gas1"]), name(gases["gas2"])
            return {"resource": g1 if g1 == g2 else f"{g1} or {g2}",
                    "basis": f"{planet['biome']} biome: Gas1 {g1}, Gas2 {g2}"}
        if subs:
            named = [name(s) for s in subs]
            return {"resource": named[0], "likely": True, "alternatives": named[1:],
                    "basis": "assumed the planet's common resource (Mineral1); Mineral2/3 would be " + " or ".join(named[1:])}
        return {"resource": None, "basis": "planet resources not known yet"}

    def for_planet(self, address: int, tables: dict) -> list:
        ext = tables.get("extraction") or {}
        rate = ext.get("items_per_hour_by_class") or {}
        power = ((ext.get("hotspots") or {}).get("Power") or {}).get("class_strength") or {}
        out = []
        for f in self.rows.values():
            if f["address"] != address:
                continue
            key = self.key(f)
            out.append({"kind": f["kind"], "name": f["name"], "w": [round(c, 1) for c in f["w"]], "key": key,
                        "first": f["first"], "last": f["last"], "class": (self.labels.get(key) or {}).get("class"),
                        "class_source": "you" if key in self.labels else None, "has_raw": bool(f.get("raw")),
                        "rates": power if f["kind"] == "hotspot-power" else rate,
                        "rate_unit": "kP" if f["kind"] == "hotspot-power" else "items/h per extractor",
                        **self.resource(f, tables)})
        return out
