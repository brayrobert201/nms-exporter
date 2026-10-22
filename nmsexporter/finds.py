"""Hotspots and resource deposits found in game, for the /map "finds" layer.

Source: pymhf_mods/visor_log.py's visor-YYYYMMDD.jsonl, as copied into nms-db
(db.py: duplicates of a marker dropped on the way in). The game adds a
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
- mineral: any of the planet's three substances (Mineral1-3). Seen: the common
  one on Pondal IX (Activated Indium), the rare one on Okyota Gamma (Silver).
  The map lists the three until the player records which (POST /api/finds/class).
The class (C/B/A/S) is not in the marker at all: a class B power and a class S
gas marker differ only in position, label and type. The player records it
from the visor, either on the map (POST /api/finds/class, kept in
nms-db table find_label) or in game with the chat command `/hs S silver`
(visor_log writes a "label" event with the player's position; it applies to
the nearest hotspot within CHAT_LABEL_M). Chat labels stay in the log and are
never copied into find_label; per field, the newer of the two wins, so
a correction on the map is not undone by replaying an older chat label.
`/mark name` adds a named point ("mark" finds).

Planet facts (biome, substances) come from live.json's weather block and are
kept in nms-db (planet_facts) so they outlive both the visit and an exporter
restart. Reads go to nms-db and raise when it is unreachable.
"""
from __future__ import annotations

import bisect
import math

from . import db

TYPES = {"MineralHotspot": "hotspot-mineral", "GasHotspot": "hotspot-gas", "PowerHotspot": "hotspot-power",
         "TerrainResource": "deposit"}
MERGE_M = 5.0
CHAT_LABEL_M = 50.0


class Finds:
    def __init__(self, live_dir: str):
        self.dir = live_dir
        self._last = 0
        self.rows: dict = {}          # (address, kind, rounded position) -> find
        self._pending: list = []      # marker rows seen before the trail covered their time
        self.chat: list = []          # /hs labels: {"address", "rel", "t", "class", "resource"}
        self.planets: dict = {}       # address (int) -> planet facts (nms-db planet_facts)
        self.labels: dict = {}        # find key -> {"class": "B"} (nms-db find_label)
        self._loaded = False

    def remember_planet(self, address: int | None, planet: dict | None):
        if address is None or not planet or not planet.get("substances"):
            return
        keep = {k: planet.get(k) for k in ("substances", "biome", "weather", "storm_frequency", "intensity", "tile_colours")}
        if self.planets.get(address) == keep:
            return
        try:
            db.put_planet(address, keep)
            self.planets[address] = keep
        except Exception:      # noqa: BLE001 - tried again on the next live sample
            pass

    def refresh(self, timeline: list):
        """timeline: sorted [(t, address)] of planet changes from the trail."""
        if not self._loaded:
            self.labels, self.planets, self._loaded = db.labels(), db.planets(), True
        new = self._pending
        self._pending = []
        self._last, rows = db.tail("visor", self._last)
        for _, r in rows:
            if (r.get("event") == "marker_add" and r.get("type") in TYPES and r.get("rel")) \
                    or (r.get("event") in ("label", "mark") and r.get("rel")):
                new.append(r)
        times = [t for t, _ in timeline]
        for r in new:
            i = bisect.bisect_right(times, r["t"]) - 1
            if i < 0:
                self._pending.append(r)
                continue
            address = timeline[i][1]
            if r["event"] == "label":
                self.chat.append({"address": address, "rel": r["rel"], "t": r["t"],
                                  "class": r.get("class"), "resource": r.get("resource")})
                continue
            kind = "mark" if r["event"] == "mark" else TYPES[r["type"]]
            key = (address, kind) + tuple(round(c / MERGE_M) for c in r["rel"])
            f = self.rows.get(key)
            if f is None:
                self.rows[key] = {"kind": kind, "name": r.get("name"), "w": list(r["rel"]), "address": address,
                                  "first": r["t"], "last": r["t"], "raw": r.get("raw")}
            else:
                f["last"] = max(f["last"], r["t"])
                f["raw"] = f["raw"] or r.get("raw")

    @staticmethod
    def key(f: dict) -> str:
        return f"{f['address']:X}:{f['kind']}:" + ":".join(str(round(c / MERGE_M)) for c in f["w"])

    def set_label(self, key: str, **fields) -> bool:
        """Record what the visor showed: class (C/B/A/S) and/or resource; None clears a field."""
        if "class" in fields and fields["class"] not in (None, "C", "B", "A", "S"):
            return False
        if not any(self.key(f) == key for f in self.rows.values()):
            return False
        lab = dict(self.labels.get(key) or {})
        for k, v in fields.items():
            if v:
                lab[k] = v
            else:
                lab.pop(k, None)
        lab.pop("t", None)
        if lab:
            self.labels[key] = {**lab, "t": round(__import__("time").time())}
        else:
            self.labels.pop(key, None)
        db.put_label(key, self.labels.get(key))
        return True

    def resource(self, f: dict, tables: dict) -> dict:
        items = tables.get("items") or {}
        name = lambda i: (items.get(i) or {}).get("name") or i  # noqa: E731
        planet = self.planets.get(f["address"]) or {}
        subs = planet.get("substances") or []
        if f["kind"] == "mark":
            return {"resource": f["name"], "basis": "your mark (/mark)"}
        if f["kind"] == "deposit":
            return {"resource": (f["name"] or "").replace(" Deposit", "") or None, "basis": "the deposit's name"}
        if f["kind"] == "hotspot-power":
            return {"resource": "Power", "basis": "hotspot type"}
        if f["kind"] == "hotspot-gas":
            gases = ((tables.get("extraction") or {}).get("biome_gases") or {}).get(planet.get("biome") or "")
            if not gases:
                return {"resource": None, "basis": "planet biome not known yet"}
            g1, g2 = name(gases["gas1"]), name(gases["gas2"])
            return {"resource": g1 if g1 == g2 else f"{g1} or {g2}", "options": [g1] if g1 == g2 else [g1, g2],
                    "basis": f"{planet['biome']} biome: Gas1 {g1}, Gas2 {g2}"}
        if subs:
            named = [name(s) for s in subs]
            return {"resource": " or ".join(named), "options": named,
                    "basis": "one of the planet's three resources; the visor says which"}
        return {"resource": None, "basis": "planet resources not known yet"}

    def chat_labels(self, address: int) -> tuple[dict, list]:
        """{find key: {field: (t, value)}} from /hs commands on this planet, and those
        that found no hotspot within CHAT_LABEL_M."""
        hotspots = [f for f in self.rows.values() if f["address"] == address and f["kind"].startswith("hotspot")]
        out: dict = {}
        unmatched = []
        for c in self.chat:
            if c["address"] != address:
                continue
            near = min(hotspots, key=lambda f: math.dist(f["w"], c["rel"]), default=None)
            if near is None or math.dist(near["w"], c["rel"]) > CHAT_LABEL_M:
                unmatched.append({"t": c["t"], "class": c["class"], "resource": c["resource"]})
                continue
            fields = out.setdefault(self.key(near), {})
            for k in ("class", "resource"):
                if c.get(k) and (k not in fields or fields[k][0] < c["t"]):
                    fields[k] = (c["t"], c[k])
        return out, unmatched

    def for_planet(self, address: int, tables: dict) -> list:
        ext = tables.get("extraction") or {}
        rate = ext.get("items_per_hour_by_class") or {}
        power = ((ext.get("hotspots") or {}).get("Power") or {}).get("class_strength") or {}
        chat, _ = self.chat_labels(address)
        out = []
        for f in self.rows.values():
            if f["address"] != address:
                continue
            key = self.key(f)
            lab = dict(self.labels.get(key) or {})
            res = self.resource(f, tables)
            for k, (t, v) in chat.get(key, {}).items():      # newer of map and chat wins, per field
                if k not in lab or lab.get("t", 0) < t:
                    if k == "resource":
                        # "nit" -> Nitrogen: match what this hotspot can give
                        v = next((o for o in res.get("options") or [] if o.lower().startswith(v.lower())), v.title())
                    lab[k] = v
            if lab.get("resource"):
                res.update(resource=lab["resource"], basis="recorded by you from the visor")
            out.append({"kind": f["kind"], "name": f["name"], "w": [round(c, 1) for c in f["w"]], "key": key,
                        "first": f["first"], "last": f["last"], "class": lab.get("class"),
                        "class_source": "you" if lab.get("class") else None, "has_raw": bool(f.get("raw")),
                        "rates": power if f["kind"] == "hotspot-power" else rate,
                        "rate_unit": "kP" if f["kind"] == "hotspot-power" else "items/h per extractor",
                        **res})
        return out
