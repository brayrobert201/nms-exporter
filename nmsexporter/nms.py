"""No Man's Sky save collector: metrics with wall-clock projection.

The save is an *anchor*, not a feed. Everything with a rate (refiners,
extractors, plants, frigate expeditions) is projected forward from the
save's own timestamps, so numbers keep moving between autosaves and while the
game is closed. When a new save lands, the anchor jumps back to the truth.

Reads: the newest save*.hg in the Steam/Proton save directory, data/nms_tables.json
(recipes, item names, rates - built by scripts/nms-extract-tables.py) and
data/nms_mapping.json (key de-obfuscation). Writes: a small state file with
fill-level history so extraction rates can be *measured* rather than assumed.
Standard library only; every error is captured into the snapshot's `errors`.
"""
from __future__ import annotations

import glob
import json
import math
import os
import re
import threading
import time
import urllib.request

from . import nmssave
from .planner import Planner
from .crafting import Crafting

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

# --- configuration (env overrides) -------------------------------------------
_HOMES = [os.path.expanduser("~")] + sorted(glob.glob("/home/*"))
_SAVE_GLOB = "/.local/share/Steam/steamapps/compatdata/275850/pfx/drive_c/users/steamuser/AppData/Roaming/HelloGames/NMS/st_*"
SAVE_DIR = os.environ.get("NMS_SAVE_DIR", "")
TABLES = os.environ.get("NMS_TABLES", os.path.join(ROOT, "data", "nms_tables.json"))
STORAGE_PLAN = os.environ.get("NMS_STORAGE_PLAN", os.path.join(ROOT, "data", "nms_storage_plan.json"))
_state_root = os.environ.get("STATE_DIRECTORY") or os.path.expanduser("~/.cache/nms-exporter")
_cache_root = os.environ.get("CACHE_DIRECTORY") or _state_root
STATE_FILE = os.environ.get("NMS_STATE", os.path.join(_state_root, "nms_state.json"))
MAPPING_CANDIDATES = [os.environ.get("NMS_MAPPING", ""),
                      os.path.join(_cache_root, "mapping.json"),
                      os.path.join(ROOT, "data", "nms_mapping.json")]

RESOURCE_KINDS = {"^U_EXTRACTOR_S": "mineral", "^U_GASEXTRACTOR": "gas", "^U_SILO_S": "depot"}
EXTRACTORS = {"^U_EXTRACTOR_S", "^U_GASEXTRACTOR"}
GAS_SUBSTANCES = {"GAS1", "GAS2", "GAS3", "GAS4", "OXYGEN"}   # what a gas extractor can yield
SUBSTANCE_STACK = 9999          # refiner output cap for substances
REFINER_STALE_SECONDS = 7 * 86400   # ignore refiner entries not touched for a week
PLANT_NAMES = {"RADIOPLANT": "Gamma Weed", "TOXICPLANT": "Fungal Cluster", "SNOWPLANT": "Frostwort",
               "SACVENOMPLANT": "Venom Urchin", "SCORCHEDPLANT": "Solar Vine", "POOPPLANT": "Coprite Sphere",
               "GRAVPLANT": "Gravitino Host", "CREATUREPLANT": "Mordite Root", "BARRENPLANT": "Echinocactus",
               "LUSHPLANT": "Star Bramble", "PEARLPLANT": "Albumen Pearl Orb", "NIPPLANT": "NipNip Buds"}
# What each planted base part yields when harvested (item id in the tables).
PLANT_YIELDS = {"RADIOPLANT": "PLANT_RADIO", "TOXICPLANT": "PLANT_TOXIC", "SNOWPLANT": "PLANT_SNOW",
                "SACVENOMPLANT": "SACVENOM", "SCORCHEDPLANT": "PLANT_HOT", "POOPPLANT": "PLANT_POOP",
                "GRAVPLANT": "GRAVBALL", "CREATUREPLANT": "CREATURE1", "BARRENPLANT": "PLANT_DUST",
                "LUSHPLANT": "PLANT_LUSH", "PEARLPLANT": "ALBUMENPEARL", "NIPPLANT": "NIPNIPBUDS"}
def _centre(objs: list) -> list:
    return [sum(o["Position"][i] for o in objs) / len(objs) for i in range(3)]


def _dist(a, b) -> float:
    return math.dist(a, b)


def _pipe_networks(units: list, pipes: list, tol: float = 3.2, unit_tol: float = 0.0) -> list:
    """Connected components of extractors and depots joined by pipeline
    segments. A U_PIPELINE's Position is one end and Position + At the other
    (At is not normalised; its length is the segment length). Ends within
    `tol` of a unit or of another pipe end are joined (the game's connection
    distance is 3). Joining units that merely touch (`unit_tol`) is off by
    default: it lumps neighbouring networks' depot rows together. Geometry is
    the whole answer: fills are NOT a connection signal. Units on one network
    gain in lockstep but keep the offsets they started with, so a working
    network shows many fills (Cobalt Oxygen, two saves 204 s apart: three
    traced networks, every unit in each rising by the same amount). An
    earlier split-by-fill step invented a dozen one-extractor networks there."""
    parent: dict = {}

    def find(x):
        while parent.setdefault(x, x) != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        parent[find(a)] = find(b)

    ends = []
    for i, p in enumerate(pipes):
        a = p["Position"]
        ends.append((i, a))
        ends.append((i, [a[k] + p["At"][k] for k in range(3)]))
    for i, e in ends:
        for j, u in enumerate(units):
            if _dist(e, u["Position"]) < tol:
                union(("p", i), ("u", j))
        for i2, e2 in ends:
            if i2 != i and _dist(e, e2) < tol:
                union(("p", i), ("p", i2))
    if unit_tol > 0:
        for j in range(len(units)):
            for k in range(j + 1, len(units)):
                if _dist(units[j]["Position"], units[k]["Position"]) < unit_tol:
                    union(("u", j), ("u", k))
    comps: dict = {}
    for j, u in enumerate(units):
        comps.setdefault(find(("u", j)), []).append(u)
    return list(comps.values())


GAME_MODES = {1: "Normal", 2: "Creative", 3: "Survival", 4: "Permadeath", 5: "Ambient"}

# RefinerBufferKeys are GcMaintenanceSaveKey: a position and an integer Location.
# libMBIN has no enum for it; these were read off a save, see README.
LOCATION_NAMES = {1: "Planet surface", 2: "Freighter", 3: "Planet base", 5: "Space", 6: "Frigate", 8: "Corvette"}
# Mission IDs that are hints, wiki pages or lore flags rather than missions.
MISSION_SKIP = re.compile(r"_HINT$|_WIKI$|_LORE$|_LORE_$|_DUMMY$|_FIX$|_FIX_\d$|_CLEAN$|HELP$|^DM_|^D_NEXUS|^WM_|^COMM_|^S\d\d_|CATCHUP")
MISSION_COMPLETE = 2147483647
CLASS_RANK = {"X": 5, "S": 4, "A": 3, "B": 2, "C": 1}
# VehicleOwnership is indexed by GcVehicleType: Buggy, Bike, Truck, WheeledBike, Hovercraft, Submarine, Mech.
VEHICLE_NAMES = ["Roamer", "Nomad", "Colossus", "Pilgrim", "Hovercraft", "Nautilon", "Minotaur"]

CONTAINER_KEYS = [  # (PlayerStateData key, location label)
    ("Inventory", "Exosuit"), ("Inventory_Cargo", "Exosuit cargo"),
    ("FreighterInventory", "Freighter"), ("FreighterInventory_Cargo", "Freighter cargo"),
    ("ChestMagicInventory", "Storage (magic)"), ("ChestMagic2Inventory", "Storage (magic 2)"),
    ("CookingIngredientsInventory", "Cooking ingredients"), ("CorvetteStorageInventory", "Corvette storage"),
    ("FishPlatformInventory", "Fish platform"), ("FishBaitBoxInventory", "Bait box"),
    ("FoodUnitInventory", "Food unit"),
] + [(f"Chest{i}Inventory", f"Storage {i}") for i in range(1, 11)]


def find_save_dir() -> str:
    if SAVE_DIR:
        return SAVE_DIR
    for home in _HOMES:
        hits = sorted(glob.glob(home + _SAVE_GLOB))
        if hits:
            return hits[0]
    return ""


def newest_save(save_dir: str) -> str:
    saves = [p for p in glob.glob(os.path.join(save_dir, "save*.hg")) if os.path.getsize(p) > 0]
    return max(saves, key=os.path.getmtime) if saves else ""


def _load_mapping() -> dict:
    for p in MAPPING_CANDIDATES:
        if p and os.path.exists(p):
            return nmssave.load_mapping(p)
    target = MAPPING_CANDIDATES[1]
    os.makedirs(os.path.dirname(target), exist_ok=True)
    urllib.request.urlretrieve(nmssave.MAPPING_URL, target)
    return nmssave.load_mapping(target)


def _stat_value(v) -> float | None:
    if not isinstance(v, dict):
        return None
    if "IntValue" in v:
        return v["IntValue"]
    if "FloatValue" in v:
        return v["FloatValue"]
    return 0 if v == {} else None


class Collector:
    """Decodes the newest save on change and serves projected metrics."""

    def __init__(self):
        self._lock = threading.Lock()
        self.snapshot: dict = {"errors": {"save": "not loaded yet"}}
        self._loaded_path, self._loaded_mtime = "", 0.0
        self.tables = self._load_tables()
        self.crafting = Crafting(self.tables)
        self.planner = Planner(self.tables.get("items", {}), self.tables.get("crops", {}))
        self.raw_bases: list = []
        self.raw_points: dict = {}
        self.crafting_result: dict = {}
        self.crafting_seconds = 0.0
        self.mapping: dict = {}
        self.state = self._load_state()
        self.decode_seconds = 0.0
        self.decodes, self.decode_failures = 0, 0

    # -- files ---------------------------------------------------------------
    def _load_tables(self) -> dict:
        try:
            with open(TABLES) as fh:
                return json.load(fh)
        except Exception as e:
            # not in git (game text): built from the installed game by scripts/nms-extract-tables.py
            return {"errors": f"{e} - run scripts/nms-extract-tables.py", "items": {}, "recipes": [], "buildings": {}, "fleet": {}, "extraction": {}}

    def _load_state(self) -> dict:
        try:
            with open(STATE_FILE) as fh:
                return json.load(fh)
        except Exception:
            return {"farms": {}}

    def _save_state(self):
        try:
            os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
            tmp = STATE_FILE + ".tmp"
            with open(tmp, "w") as fh:
                json.dump(self.state, fh)
            os.replace(tmp, STATE_FILE)
        except Exception as e:
            self.snapshot.setdefault("errors", {})["state"] = str(e)

    # -- refresh -------------------------------------------------------------
    def refresh(self):
        """Re-decode if the newest save changed. Cheap when it has not."""
        with self._lock:
            save_dir = find_save_dir()
            path = newest_save(save_dir) if save_dir else ""
            if not path:
                self.snapshot = {"errors": {"save": f"no save files under {save_dir or '(no save dir found)'}"}}
                return
            mtime = os.path.getmtime(path)
            if path == self._loaded_path and mtime == self._loaded_mtime:
                return
            if time.time() - mtime < 2:      # the game may still be writing it
                return
            t0 = time.time()
            try:
                if not self.mapping:
                    self.mapping = _load_mapping()
                save = nmssave.decode_save(path, self.mapping)
                snap = self._build(save, path, mtime)
            except Exception as e:
                self.decode_failures += 1
                self.snapshot.setdefault("errors", {})["save"] = f"{os.path.basename(path)}: {e}"
                self._loaded_path, self._loaded_mtime = path, mtime   # do not retry a broken file every scrape
                return
            self.decode_seconds = time.time() - t0
            self.decodes += 1
            self._loaded_path, self._loaded_mtime = path, mtime
            self.snapshot = snap
            self._record_history(snap)
            self._save_state()
            threading.Thread(target=self._compute_crafting, args=(snap,), daemon=True).start()

    HISTORY_KEEP = 48

    def _record_history(self, snap: dict):
        """A compact record per decoded save, so /diff can say what changed."""
        try:
            rec = {"timestamp": snap["save"]["timestamp"], "file": snap["save"]["file"],
                   "units": snap["player"]["units"], "nanites": snap["player"]["nanites"],
                   "items": {iid: r["total"] for iid, r in snap["items"].items()},
                   "farms": {k: round(f["stored_items"]) for k, f in snap["farms"].items()}}
            hist = self.state.setdefault("history", [])
            if hist and hist[-1]["timestamp"] == rec["timestamp"] and hist[-1]["file"] == rec["file"]:
                hist[-1] = rec
            else:
                hist.append(rec)
            del hist[:-self.HISTORY_KEEP]
        except Exception as e:
            snap.setdefault("errors", {})["history"] = str(e)

    def diff(self, against: int = 1) -> dict:
        """What changed between the latest save and the one `against` saves
        earlier (1 = the previous save). Items sorted by absolute change."""
        hist = self.state.get("history", [])
        if len(hist) < 2:
            return {"error": "fewer than two saves recorded yet", "recorded": len(hist)}
        against = max(1, min(against, len(hist) - 1))
        a, b = hist[-1 - against], hist[-1]
        items = self.tables.get("items", {})
        rows = []
        for iid in set(a["items"]) | set(b["items"]):
            x, y = a["items"].get(iid, 0), b["items"].get(iid, 0)
            if x != y:
                rows.append({"id": iid, "item": items.get(iid, {}).get("name", iid), "from": x, "to": y, "delta": y - x})
        rows.sort(key=lambda r: -abs(r["delta"]))
        farms = [{"farm": k, "from": a["farms"].get(k, 0), "to": v, "delta": v - a["farms"].get(k, 0)}
                 for k, v in b["farms"].items() if a["farms"].get(k, 0) != v]
        return {"from": {"timestamp": a["timestamp"], "file": a["file"]},
                "to": {"timestamp": b["timestamp"], "file": b["file"]},
                "units": {"from": a["units"], "to": b["units"], "delta": b["units"] - a["units"]},
                "nanites": {"from": a["nanites"], "to": b["nanites"], "delta": b["nanites"] - a["nanites"]},
                "items": rows, "farms": farms, "recorded": len(hist), "against": against}

    def _compute_crafting(self, snap: dict):
        """Multi-level crafting search takes a few seconds; never hold a scrape for it."""
        t0 = time.time()
        try:
            stock = {iid: rec["total"] for iid, rec in snap["items"].items()}
            res = self.crafting.evaluate(stock, snap["known"]["products"], snap["known"]["recipes"])
            self.crafting_result = res
            self.crafting_seconds = time.time() - t0
            # The key already exists in the snapshot, so replacing its value is safe
            # while another thread serialises the snapshot.
            snap["crafting"] = self._crafting_summary(res, stock)
        except Exception as e:
            self.snapshot.setdefault("errors", {})["crafting"] = str(e)

    def _crafting_summary(self, res: dict, stock: dict) -> dict:
        """Known blueprints that cannot be made now, and the ingredients standing in the way."""
        nm = self.crafting.name
        blocked = []
        for iid, r in res.items():
            if r["makeable"] or not r["shortfall"]:
                continue
            if not any(x["route"] == "craft" and x["known"] for x in r["routes"]):
                continue
            sf = dict(r["shortfall"])
            blocked.append({"id": iid, "item": r["item"], "shortfall": {nm(k): v for k, v in sf.items()},
                            "shortfall_ids": sf, "kinds": len(sf), "units": sum(sf.values())})
        blocked.sort(key=lambda b: (b["kinds"], b["units"], b["item"]))
        groups: dict = {}
        for b in blocked:
            for ing, amt in b["shortfall_ids"].items():
                g = groups.setdefault(ing, {"id": ing, "ingredient": nm(ing), "have": stock.get(ing, 0), "items": []})
                g["items"].append({"item": b["item"], "short": amt, "only": b["kinds"] == 1})
        by_ing = sorted(groups.values(), key=lambda g: (-len(g["items"]), g["ingredient"]))
        for g in by_ing:
            g["items"].sort(key=lambda x: (x["short"], x["item"]))
        return {"computed_at": time.time(), "blocked": blocked[:150], "by_ingredient": by_ing[:24]}

    # -- snapshot (static part, computed once per save) ----------------------
    def _build(self, save: dict, path: str, mtime: float) -> dict:
        ps = save["BaseContext"]["PlayerStateData"]
        common = save.get("CommonStateData", {})
        items = self.tables.get("items", {})

        def name(iid: str) -> str:
            iid = iid.lstrip("^")
            if "#" in iid:                       # procedural item: "<type>#<seed>", the type may be a binary blob
                base, seed = iid.rsplit("#", 1)
                base_name = items.get(base, {}).get("name") if base.isprintable() and base.isascii() else None
                return f"{base_name or 'Procedural item'} #{seed}"
            return items.get(iid, {}).get("name") or iid

        def itype(iid: str) -> str:
            return items.get(iid.lstrip("^"), {}).get("type") or "Unknown"

        snap = {"errors": {}, "save": {}, "player": {}, "stats": {}, "collections": {},
                "items": {}, "locations": [], "refiners": [], "farms": {}, "plants": {},
                "fleet": {}, "universe": {}, "missions": {}, "tech": [], "tidy": {}, "blueprints": {},
                "crafting": {"computed_at": None, "blocked": [], "by_ingredient": []}}
        s = snap["save"]
        s.update(path=path, file=os.path.basename(path), mtime=mtime, timestamp=ps.get("TimeStamp", 0),
                 summary=ps.get("SaveSummary", ""), version=save.get("Version"), platform=save.get("Platform"),
                 game_mode=GAME_MODES.get(save["BaseContext"].get("GameMode"), str(save["BaseContext"].get("GameMode"))),
                 context=save.get("ActiveContext"),
                 difficulty=ps.get("DifficultyState", {}).get("Preset", {}).get("DifficultyPresetType"),
                 save_name=common.get("SaveName") or "")

        p = snap["player"]
        # Wallet values are uint32 in game but written as signed JSON ints, so
        # anything past 2^31 (2.1B units) reads negative.
        def wallet(v):
            return v + 2 ** 32 if isinstance(v, int) and v < 0 else v

        p.update(units=wallet(ps.get("Units")), nanites=wallet(ps.get("Nanites")),
                 quicksilver=wallet(ps.get("Specials")),
                 health=ps.get("Health"), shield=ps.get("Shield"), energy=ps.get("Energy"),
                 ship_health=ps.get("ShipHealth"), time_alive=ps.get("TimeAlive"),
                 total_play_time=common.get("TotalPlayTime"),
                 ammo={"bolt": ps.get("BoltAmmo"), "scatter": ps.get("ScatterAmmo"),
                       "pulse": ps.get("PulseAmmo"), "laser": ps.get("LaserAmmo")},
                 hazard=ps.get("Hazard", []))

        ua = ps.get("UniverseAddress", {})
        ga = ua.get("GalacticAddress", {})
        snap["universe"] = dict(galaxy=ua.get("RealityIndex"), x=ga.get("VoxelX"), y=ga.get("VoxelY"),
                                z=ga.get("VoxelZ"), system=ga.get("SolarSystemIndex"), planet=ga.get("PlanetIndex"))
        snap["universe"].update(self._address(ga))

        # lifetime counters
        for g in ps.get("Stats", []):
            if g.get("GroupId") == "^GLOBAL_STATS":
                for st in g.get("Stats", []):
                    v = _stat_value(st.get("Value"))
                    if v is not None:
                        # currency counters are unsigned 32-bit like the wallet: MONEY_EVER read
                        # -617,290,418 once units earned passed 2^31 (seen 2026-10-23). Standings
                        # (TRA_STANDING -86) and the like are genuinely signed: leave them alone.
                        sid = st["Id"].lstrip("^")
                        unsigned = isinstance(v, int) and v < 0 and any(k in sid for k in ("MONEY", "NANITES", "SPECIAL", "UNITS"))
                        snap["stats"][sid] = v + 2 ** 32 if unsigned else v

        dd = save.get("DiscoveryManagerData", {}).get("DiscoveryData-v1", {})
        snap["collections"] = dict(
            ships=sum(1 for x in ps.get("ShipOwnership", []) if x.get("Name") or x.get("Inventory", {}).get("Slots")),
            multitools=len(ps.get("Multitools", [])), pets=len(ps.get("Pets", [])), eggs=len(ps.get("Eggs", [])),
            frigates=len(ps.get("FleetFrigates", [])), bases=len(ps.get("PersistentPlayerBases", [])),
            visited_systems=len(ps.get("VisitedSystems", [])), known_tech=len(ps.get("KnownTech", [])),
            known_products=len(ps.get("KnownProducts", [])), known_recipes=len(ps.get("KnownRefinerRecipes", [])),
            known_words=len(ps.get("KnownWords", [])), discoveries=len(dd.get("Store", {}).get("Record", [])),
            vehicles=len(ps.get("VehicleOwnership", [])), settlements=sum(1 for x in ps.get("SettlementStatesV2", []) if x.get("Name")))

        snap["known"] = {"products": {k.lstrip("^") for k in ps.get("KnownProducts", [])},
                         "recipes": {k.lstrip("^") for k in ps.get("KnownRefinerRecipes", [])}}

        # inventories: per-location and aggregate
        def add_inv(inv: dict, where: str):
            for sl in inv.get("Slots", []) if isinstance(inv, dict) else []:
                ty = sl.get("Type", {}).get("InventoryType")
                if ty not in ("Product", "Substance"):
                    continue
                iid = sl["Id"]
                snap["locations"].append({"location": where, "id": iid.lstrip("^"), "item": name(iid),
                                          "type": ty, "amount": sl["Amount"]})
                rec = snap["items"].setdefault(iid.lstrip("^"), {"item": name(iid), "type": ty, "total": 0, "stacks": 0, "locations": 0})
                rec["total"] += sl["Amount"]
                rec["stacks"] += 1

        for key, where in CONTAINER_KEYS:
            add_inv(ps.get(key, {}), where)
        for i, sh in enumerate(ps.get("ShipOwnership", [])):
            label = f"Ship {i + 1}: {sh.get('Name') or 'unnamed'}"
            add_inv(sh.get("Inventory", {}), label)
            add_inv(sh.get("Inventory_Cargo", {}), label + " (cargo)")
        for i, v in enumerate(ps.get("VehicleOwnership", [])):
            add_inv(v.get("Inventory", {}), f"Exocraft {i + 1}: {v.get('Name') or 'unnamed'}")
        for iid, rec in snap["items"].items():
            rec["locations"] = len({l["location"] for l in snap["locations"] if l["id"] == iid})

        # refiners: newest buffer entry per position, recipe matched from slots
        snap["refiners"] = self._refiners(ps, name, itype)

        # extraction farms and plants
        snap["farms"], snap["plants"] = self._bases(ps, name)

        # device planner: what the stock and the next harvest support
        try:
            stock = {iid: rec["total"] for iid, rec in snap["items"].items()}
            snap["planner"] = self.planner.plan(stock, snap["known"]["products"], snap["plants"])
        except Exception as e:
            snap["errors"]["planner"] = str(e)
            snap["planner"] = {}

        # the base objects themselves, for /raw/bases (positions, fills, timestamps)
        self.raw_bases = [{k: b.get(k) for k in ("Name", "BaseType", "GalacticAddress", "Position", "Forward",
                                                  "LastUpdateTimestamp", "Objects")}
                          for b in ps.get("PersistentPlayerBases", [])]
        # other planet-surface positions, for /api/map
        self.raw_points = {
            "vehicles": [{"Location": v.get("Location"), "Position": v.get("Position")}
                         for v in ps.get("VehicleOwnership", [])],
            "deposits": ps.get("DrainedTerrainResourceDeposits", []),
            "settlements": [{"UniverseAddress": s.get("UniverseAddress"), "Position": s.get("Position"),
                             "Name": s.get("Name")} for s in ps.get("SettlementStatesV2", [])],
            # one bit per portal glyph 0-F (15 = Sunset, Bird, Face, Diplo: confirmed in game 2026-10-22)
            "known_runes": ps.get("KnownPortalRunes"),
        }

        # missions, against the game's mission tables
        snap["missions"] = self._missions(ps)

        # installed technology and how well it is placed
        snap["tech"] = self._tech(ps, name)

        # storage against the plan, and the blueprints the player knows
        snap["tidy"] = self._tidy(ps, name)
        snap["blueprints"] = {
            iid: {"item": name(iid), "yield": items[iid]["craft"]["yield"],
                  "ingredients": [{"id": i["id"], "item": name(i["id"]), "amount": i["amount"]}
                                  for i in items[iid]["craft"]["ingredients"]]}
            for iid in snap["known"]["products"] if items.get(iid, {}).get("craft")}

        # fleet
        fleet = self.tables.get("fleet", {})
        ev_s = fleet.get("event_seconds", 5400)
        fr = ps.get("FleetFrigates", [])
        exps = []
        for i, e in enumerate(ps.get("FleetExpeditions", [])):
            events = e.get("Events", [])
            n = len(events)
            done = int(e.get("NextEventToTrigger", 0))
            exps.append(dict(
                index=i, category=e.get("ExpeditionCategory", {}).get("ExpeditionCategory", "?"),
                duration=e.get("ExpeditionDuration", {}).get("ExpeditionDuration", "?"),
                start=e.get("StartTime", 0), events=n, events_done=done,
                events_succeeded=int(e.get("NumberOfSuccessfulEventsThisExpedition", 0)),
                events_failed=int(e.get("NumberOfFailedEventsThisExpedition", 0)),
                frigates=len(e.get("ActiveFrigateIndices", [])),
                damaged=len(e.get("DamagedFrigateIndices", [])), destroyed=len(e.get("DestroyedFrigateIndices", [])),
                eta=e.get("StartTime", 0) + n * ev_s, event_seconds=ev_s,
                event_ids=[x.get("EventID", "").lstrip("^") for x in events],
                event_success=[bool(x.get("Success")) for x in events]))
        snap["fleet"] = dict(frigates=len(fr), expeditions=exps,
                             frigate_classes={}, roster=self._frigates(ps))
        for f in fr:
            c = f.get("FrigateClass", {}).get("FrigateClass", "?")
            snap["fleet"]["frigate_classes"][c] = snap["fleet"]["frigate_classes"].get(c, 0) + 1
        return snap

    @staticmethod
    def _base_name(ps: dict, b: dict) -> str:
        t = b.get("BaseType", {}).get("PersistentBaseTypes")
        if t == "FreighterBase":
            return f"Freighter {ps.get('PlayerFreighterName') or ''}".strip()
        if t == "PlayerShipBase":
            return "Corvette"
        return b.get("Name") or t or "base"

    @staticmethod
    def _planet_base_refiners(ps: dict) -> list:
        """(position, base name) of every refiner built in a planetary base, in the
        frame the maintenance keys use: relative to the base origin, with the axes
        of the planet rather than of the base (Up = the base's position from the
        planet centre, Forward = the base's Forward made orthogonal to it)."""
        def norm(v):
            n = math.sqrt(sum(x * x for x in v))
            return [x / n for x in v] if n else None

        out = []
        for b in ps.get("PersistentPlayerBases", []):
            if b.get("BaseType", {}).get("PersistentBaseTypes") in ("FreighterBase", "PlayerShipBase"):
                continue
            up = norm(b.get("Position") or [0, 0, 0])
            fwd = b.get("Forward") or [0, 0, 1]
            if not up:
                continue
            d = sum(a * c for a, c in zip(fwd, up))
            f = norm([fwd[i] - d * up[i] for i in range(3)])
            if not f:
                continue
            r = norm([up[1] * f[2] - up[2] * f[1], up[2] * f[0] - up[0] * f[2], up[0] * f[1] - up[1] * f[0]])
            for o in b.get("Objects", []):
                if "REFINER" not in (o.get("ObjectID") or ""):
                    continue
                p = o.get("Position") or [0, 0, 0]
                out.append(([r[i] * p[0] + up[i] * p[1] + f[i] * p[2] for i in range(3)], b.get("Name") or "base"))
        return out

    def _refiners(self, ps: dict, name, itype) -> list:
        planet_refiners = self._planet_base_refiners(ps)

        def place(loc, kpos) -> str:
            if loc == 2:
                return f"Freighter {ps.get('PlayerFreighterName') or ''}".strip()
            if loc == 3 and planet_refiners:
                best = min(planet_refiners, key=lambda x: math.dist(x[0], kpos))
                if math.dist(best[0], kpos) < 2.0:
                    return best[1]
            return LOCATION_NAMES.get(loc, f"location {loc}")

        recipes = [r for r in self.tables.get("recipes", []) if not r.get("cooking")]
        by_result: dict = {}
        for r in recipes:
            by_result.setdefault(r["result"]["id"], []).append(r)
        newest: dict = {}
        for k, d in zip(ps.get("RefinerBufferKeys", []), ps.get("RefinerBufferData", [])):
            key = (k.get("Location"), tuple(int(round(x)) for x in k.get("Position", [])))
            if key not in newest or d.get("LastUpdateTimestamp", 0) > newest[key][1].get("LastUpdateTimestamp", 0):
                newest[key] = (k, d)
        out = []
        cutoff = time.time() - REFINER_STALE_SECONDS
        for (loc, pos), (k, d) in newest.items():
            all_slots = d.get("InventoryContainer", {}).get("Slots", [])
            if any(s.get("Id") == "^MAINT_HOOVER" for s in all_slots):
                continue                      # a gas/mineral extractor room, not a refiner
            if d.get("LastUpdateTimestamp", 0) < cutoff:
                continue
            slots = [s for s in all_slots if s.get("Type", {}).get("InventoryType") in ("Product", "Substance")]
            if not slots:
                continue
            ids = {s["Id"].lstrip("^"): s for s in slots}
            # Which slot is the output? An Amount of -1 is the game's "chosen but
            # nothing made yet" placeholder and settles it; otherwise score the
            # candidates: the recipe whose ingredients are exactly the other slots
            # wins, and one whose result is also an ingredient (e.g. Oxygenate
            # Carbon) only wins when nothing else fits.
            match = None
            for out_id, s in ids.items():
                others = set(ids) - {out_id}
                for r in by_result.get(out_id, []):
                    need = {i["id"] for i in r["ingredients"]}
                    if not (need <= others or need <= set(ids)):
                        continue
                    score = (20 if s["Amount"] == -1 else 0) + (10 if need == others else 0) \
                        + (5 if need <= others else 0) + (1 if out_id not in need else 0)
                    if match is None or score > match[0]:
                        match = (score, r, out_id)
            if not match:
                continue
            _, r, out_id = match
            out_slot = ids[out_id]
            inputs = []
            ops = None
            for ing in r["ingredients"]:
                sl = ids.get(ing["id"])
                amt = max(0, sl["Amount"]) if sl else 0
                inputs.append({"id": ing["id"], "item": name(ing["id"]), "amount": amt, "per_op": ing["amount"]})
                n = amt // ing["amount"] if ing["amount"] else 0
                ops = n if ops is None else min(ops, n)
            out.append(dict(
                key=f"{loc}:{pos[0]},{pos[1]},{pos[2]}", location_code=loc,
                base=place(loc, k.get("Position") or [0, 0, 0]),
                recipe=r["operation"], recipe_id=r["id"], seconds_per_op=r["seconds_per_op"],
                output_id=out_id, output=name(out_id), output_amount=max(0, out_slot["Amount"]),
                output_per_op=r["result"]["amount"],
                output_cap=SUBSTANCE_STACK if itype(out_id) == "Substance" else (out_slot.get("MaxAmount") or 0),
                inputs=inputs, ops_remaining=ops or 0,
                last_update=d.get("LastUpdateTimestamp", 0), last_completed=d.get("LastCompletedTimestamp", 0)))
        return out

    def _farm_rows(self, bname: str, objs: list, cap_units: dict, upi: float, base_stamp: int) -> dict:
        """One farm row per pipe network in a base. Networks are traced from the
        pipeline segments (each is a start Position and an At vector to its end),
        so a Radon pipe that runs 500u to a depot field by the Dioxite extractors
        is counted with Radon, not with whatever is nearer. Depots on no network
        with an extractor are reported with the nearest one. With no pipes at
        all the extractors are grouped by type and depots by proximity. The save
        stores nothing about what a hotspot yields, so the row's name comes from
        the resource words in the base name ("Copper Oxygen")."""
        res = [o for o in objs if o.get("ObjectID") in RESOURCE_KINDS]
        pipes = [o for o in objs if o.get("ObjectID") == "^U_PIPELINE"]
        comps = _pipe_networks(res, pipes) if pipes else []
        groups = []
        if comps:
            with_ext = [c for c in comps if any(o["ObjectID"] in EXTRACTORS for o in c)]
            orphans = [o for c in comps if c not in with_ext for o in c]
            for o in orphans:                       # a depot cluster nobody pipes to
                if with_ext:
                    min(with_ext, key=lambda c: _dist(o["Position"], _centre(c))).append(o)
            for c in with_ext:
                gas = sum(o["ObjectID"] == "^U_GASEXTRACTOR" for o in c)
                mineral = sum(o["ObjectID"] == "^U_EXTRACTOR_S" for o in c)
                groups.append(("gas" if gas >= mineral else "mineral", c))
        else:
            mins = [o for o in res if o["ObjectID"] == "^U_EXTRACTOR_S"]
            gases = [o for o in res if o["ObjectID"] == "^U_GASEXTRACTOR"]
            depots = [o for o in res if o["ObjectID"] == "^U_SILO_S"]
            if mins and gases:
                cm, cg = _centre(mins), _centre(gases)
                near_m = [d for d in depots if _dist(d["Position"], cm) <= _dist(d["Position"], cg)]
                groups = [("mineral", mins + near_m), ("gas", gases + [d for d in depots if d not in near_m])]
            else:
                groups = [("gas" if gases else "mineral", res)]
        groups.sort(key=lambda kc: -sum(o["ObjectID"] in EXTRACTORS for o in kc[1]))
        words = self._farm_words(bname)
        rows = {}
        seen: dict = {}
        for kind, group in groups:
            split = len(groups) > 1
            n = seen[kind] = seen.get(kind, 0) + 1
            suffix = f" {n}" if n > 1 else ""
            name = (" ".join(words[kind]) or (f"{bname} ({kind})" if split else bname)) + suffix
            key = (f"{bname} \u00b7 {kind}" if split else bname) + suffix
            f = {"base": bname, "name": name, "kind": kind, "extractors": 0, "gas_extractors": 0, "depots": 0,
                 "stored_units": 0, "capacity_units": 0, "anchor": base_stamp}
            for o in group:
                oid = o["ObjectID"]
                f["extractors" if oid == "^U_EXTRACTOR_S" else "gas_extractors" if oid == "^U_GASEXTRACTOR" else "depots"] += 1
                f["stored_units"] += (o.get("UserData", 0) >> 32)
                f["capacity_units"] += cap_units[oid]
                f["anchor"] = max(f["anchor"], o.get("Timestamp", 0))
            f["stored_items"] = f["stored_units"] / upi
            f["capacity_items"] = f["capacity_units"] / upi
            rows[key] = f
        return rows

    def _farm_words(self, bname: str) -> dict:
        """Substance names found in a base name, split by whether a gas or a
        mineral extractor yields them. Longest names match first so
        "Magnetised Ferrite" is not read as "Ferrite"."""
        if not hasattr(self, "_substance_names"):
            items = self.tables.get("items", {})
            subs = [(v["name"].lower(), k) for k, v in items.items() if v.get("type") == "Substance" and v.get("name")]
            self._substance_names = sorted(subs, key=lambda kv: -len(kv[0]))
        low = " " + re.sub(r"[^a-z0-9]+", " ", bname.lower()) + " "
        found = {"mineral": [], "gas": []}
        for nm, iid in self._substance_names:
            if f" {nm} " in low:
                found["gas" if iid in GAS_SUBSTANCES else "mineral"].append(self.tables["items"][iid]["name"])
                low = low.replace(f" {nm} ", "  ")
        return found

    def _bases(self, ps: dict, name) -> tuple:
        ext = self.tables.get("extraction", {})
        upi = ext.get("resource_units_per_item", 1440)
        parts = self.tables.get("buildings", {})
        cap_units = {"^U_EXTRACTOR_S": parts.get("U_EXTRACTOR_S", {}).get("storage", 360000),
                     "^U_GASEXTRACTOR": parts.get("U_GASEXTRACTOR", {}).get("storage", 360000),
                     "^U_SILO_S": parts.get("U_SILO_S", {}).get("storage", 1440000)}
        plant_grow = {"^" + k: v["storage"] for k, v in parts.items() if v.get("network") == "PlantGrowth" and v.get("storage")}
        farms, plants = {}, {}
        for b in ps.get("PersistentPlayerBases", []):
            bname = self._base_name(ps, b)
            objs = b.get("Objects", [])
            if any(o.get("ObjectID") in RESOURCE_KINDS for o in objs):
                farms.update(self._farm_rows(bname, objs, cap_units, upi, b.get("LastUpdateTimestamp", 0)))
            pl = [o for o in objs if o.get("ObjectID") in plant_grow]
            if pl:
                rec = plants.setdefault(bname, {"base": bname, "plants": []})
                for o in pl:
                    pid = o["ObjectID"].lstrip("^")
                    yid = PLANT_YIELDS.get(pid)
                    rec["plants"].append({"plant": PLANT_NAMES.get(pid, pid), "id": pid,
                                          "yield_id": yid, "yields": name(yid) if yid else None,
                                          "grown": (o.get("UserData", 0) >> 32), "grow_seconds": plant_grow[o["ObjectID"]],
                                          "anchor": o.get("Timestamp", 0)})
        # measured extraction rate from fill history (units/s), per farm
        hist = self.state.setdefault("farms", {})
        rate_default = ext.get("extractor_rate_per_s", 100)
        for bname, f in farms.items():
            samples = hist.setdefault(bname, [])
            if not samples or samples[-1][0] != f["anchor"]:
                samples.append([f["anchor"], f["stored_units"]])
                del samples[:-60]
            rate, measured = None, False
            for (t0, u0), (t1, u1) in zip(samples[-30:], samples[-29:]):
                if t1 > t0 and u1 > u0 and u1 < f["capacity_units"]:
                    rate, measured = (u1 - u0) / (t1 - t0), True   # latest positive pair wins
            if rate is None:
                rate = rate_default * (f["extractors"] + f["gas_extractors"])   # class-C, on the hotspot
            f["rate_units_per_s"], f["rate_measured"] = rate, measured
            f["rate_items_per_hour"] = rate * 3600 / upi
        return farms, plants

    @staticmethod
    def _address(ga: dict) -> dict:
        """Portal glyphs and the signal-booster style galactic address for a
        voxel address, as NMSCD/Coordinate-Conversion does it: glyphs are
        planet, system (3 hex), Y (2 hex), Z (3 hex), X (3 hex) with negatives
        wrapped; the address adds 2047 / 127 / 2047 to X / Y / Z."""
        try:
            x, y, z = int(ga.get("VoxelX", 0)), int(ga.get("VoxelY", 0)), int(ga.get("VoxelZ", 0))
            sysi, planet = int(ga.get("SolarSystemIndex", 0)), int(ga.get("PlanetIndex", 0))
        except (TypeError, ValueError):
            return {}
        glyphs = "%X%03X%02X%03X%03X" % (planet & 0xF, sysi & 0xFFF, y & 0xFF, z & 0xFFF, x & 0xFFF)
        address = "%04X:%04X:%04X:%04X" % (x + 2047, y + 127, z + 2047, sysi)
        return {"glyphs": glyphs, "address": address}

    def _frigates(self, ps: dict) -> list:
        """Each frigate with its stats, traits and a base-roll score: the stats
        as they are now, less what traits and rank-ups added (NMSCD's frigate
        calculator), clamped to the community's -5 to 14 scale."""
        fleet = self.tables.get("fleet", {})
        traits = fleet.get("traits", {})
        per_level = fleet.get("stat_points_per_level", 5)
        thresholds = fleet.get("level_thresholds_community", [4, 8, 15, 25, 30, 35, 40, 45, 50, 55])
        MAIN = ("Combat", "Exploration", "Mining", "Diplomatic")
        out = []
        for i, f in enumerate(ps.get("FleetFrigates", [])):
            st = f.get("Stats") or []
            stats = {"combat": st[0] if len(st) > 0 else 0, "exploration": st[1] if len(st) > 1 else 0,
                     "industrial": st[2] if len(st) > 2 else 0, "trade": st[3] if len(st) > 3 else 0,
                     "fuel_burn": st[4] if len(st) > 4 else 0, "fuel_capacity": st[5] if len(st) > 5 else 0,
                     "speed": st[6] if len(st) > 6 else 0}
            tids = [t.lstrip("^") for t in f.get("TraitIDs", []) if t and t != "^"]
            trait_names, trait_points = [], 0
            for t in tids:
                tr = traits.get(t)
                trait_names.append(tr["name"] if tr else t)
                if tr and tr.get("stat") in MAIN:
                    trait_points += tr.get("points", 0)
            exps = int(f.get("TotalNumberOfExpeditions", 0))
            level = sum(1 for th in thresholds if exps > th)
            main_total = stats["combat"] + stats["exploration"] + stats["industrial"] + stats["trade"]
            roll = main_total - trait_points - per_level * level
            fclass = f.get("FrigateClass", {}).get("FrigateClass", "?")
            out.append(dict(index=i, name=f.get("CustomName") or f"{fclass} frigate {i + 1}", type=fclass,
                            inventory_class=f.get("InventoryClass", {}).get("InventoryClass", "?"),
                            race=f.get("Race", {}).get("AlienRace", "?"), stats=stats, main_total=main_total,
                            traits=trait_names, trait_points=trait_points, expeditions=exps, level=level,
                            events_ok=int(f.get("TotalNumberOfSuccessfulEvents", 0)),
                            events_failed=int(f.get("TotalNumberOfFailedEvents", 0)),
                            times_damaged=int(f.get("NumberOfTimesDamaged", 0)),
                            roll=roll, score=max(-5, min(14, roll))))
        out.sort(key=lambda r: (-r["score"], -r["main_total"]))
        return out

    def _missions(self, ps: dict) -> dict:
        """Every mission in the save against the tables: status, and for the ones in
        progress the current objective and what finishing them hands out."""
        table = self.tables.get("missions") or {}
        current = (ps.get("CurrentMissionID") or "").lstrip("^")
        counts = {"in_progress": 0, "complete": 0, "not_started": 0, "unknown": 0}
        best: dict = {}        # seeded missions repeat per seed; an in-progress instance wins
        for m in ps.get("MissionProgress", []):
            mid = (m.get("Mission") or "").lstrip("^")
            if not mid or MISSION_SKIP.search(mid):
                continue
            t = table.get(mid)
            if not t:
                status = "unknown"
            else:
                prog, final = m.get("Progress", -1), t.get("final")
                if prog == -1:
                    status = "not_started"
                elif prog == MISSION_COMPLETE or (final is not None and prog >= final):
                    status = "complete"
                else:
                    status = "in_progress"
            if mid not in best or (status == "in_progress" and best[mid][0] != "in_progress"):
                best[mid] = (status, m)
        rows = []
        for mid, (status, m) in best.items():
            counts[status] += 1
            if status != "in_progress":
                continue
            t = table[mid]
            prog, final = m.get("Progress", -1), t.get("final")
            objective = ""
            for num, text in t.get("stages", []):
                if num is None or num > prog:
                    break
                objective = text
            rewards = [d for _, ds in t.get("rewards", []) for d in ds]
            rows.append(dict(id=mid, title=t["title"], progress=prog, final=final,
                             remaining=(final - prog) if final is not None else None,
                             objective=objective, rewards=rewards[:4], leads_to=t.get("leads_to", []),
                             selected=mid == current))
        rows.sort(key=lambda r: (r["remaining"] if r["remaining"] is not None else 10 ** 9, r["title"]))
        return {"current": current, "tables": bool(table), "counts": counts, "in_progress": rows}

    def _tech(self, ps: dict, name) -> list:
        """Installed technology per inventory, with the placement review: which
        supercharged slots are earning their keep, which modules deserve one
        instead, and which stat families are not touching each other."""
        items = self.tables.get("items", {})

        def short(n: str) -> str:
            return re.sub(r" #\d+$", "", n)

        def slot_class(base: str, rec: dict) -> str | None:
            if rec.get("class"):
                return rec["class"]
            m = re.search(r"(\d|X)$", base)
            return {"1": "C", "2": "B", "3": "A", "4": "S", "X": "X"}.get(m[1]) if m else None

        def review(inv: dict, label: str, primary: bool) -> dict | None:
            slots = []
            for sl in inv.get("Slots", []) if isinstance(inv, dict) else []:
                if sl.get("Type", {}).get("InventoryType") != "Technology":
                    continue
                iid = (sl.get("Id") or "").lstrip("^")
                base = iid.split("#", 1)[0]
                rec = items.get(base, {})
                slots.append({"x": sl["Index"]["X"], "y": sl["Index"]["Y"], "id": iid, "name": name(iid),
                              "family": rec.get("stat"), "class": slot_class(base, rec),
                              "procedural": bool(rec.get("procedural")), "core": bool(rec.get("core")),
                              "upgrade": bool(rec.get("upgrade")), "broken": not sl.get("FullyInstalled", True)
                              or (sl.get("DamageFactor") or 0) > 0})
            if not slots:
                return None
            special = {(sp["Index"]["X"], sp["Index"]["Y"]): sp.get("Type", {}).get("InventorySpecialSlotType")
                       for sp in inv.get("SpecialSlots", [])}
            super_xy = [xy for xy, t in special.items() if t == "TechBonus"]
            at = {(s["x"], s["y"]): s for s in slots}
            # Supercharged slots: a procedural module there is the point of them; a
            # fixed technology gains less; an empty one gains nothing.
            good, weak, empty = [], [], []
            for xy in super_xy:
                s = at.get(xy)
                if s is None:
                    empty.append(xy)
                elif s["procedural"]:
                    good.append(s)
                else:
                    weak.append(s)
            super_min = min((CLASS_RANK.get(s["class"], 0) for s in good), default=0)
            # Modules that would gain from a supercharged slot, best first.
            waiting = sorted((s for s in slots if s["procedural"] and (s["x"], s["y"]) not in special),
                             key=lambda s: -CLASS_RANK.get(s["class"], 0))
            can_move = len(weak) + len(empty)
            moves = [s for s in waiting if can_move > 0][:can_move]
            # beyond that, a better module could displace a weaker one that is supercharged
            upgrades = [s for s in waiting[len(moves):] if CLASS_RANK.get(s["class"], 0) > super_min and good]
            # Families: the adjacency bonus is for upgrade modules touching their core
            # technology or each other, so only families holding a module are
            # checked, and only modules and the core are expected to touch.
            fam: dict = {}
            for s in slots:
                if s["family"]:
                    fam.setdefault(s["family"], []).append(s)
            isolated = []
            fam_names = {}
            for f, members in fam.items():
                if len(members) < 2 or not any(m["procedural"] for m in members):
                    continue
                core = [m for m in members if m["core"]] or [m for m in members if not m["procedural"]]
                fam_names[f] = core[0]["name"] if core else re.sub(r" module.*$", "", members[0]["name"])
                for s in members:
                    if not (s["procedural"] or s["core"]):
                        continue
                    touching = any(abs(s["x"] - o["x"]) + abs(s["y"] - o["y"]) == 1 for o in members if o is not s)
                    if not touching:
                        isolated.append({"family": f, "family_name": fam_names[f], "name": s["name"], "x": s["x"], "y": s["y"]})
            return {"inventory": label, "primary": primary, "class": inv.get("Class", {}).get("InventoryClass"),
                    "width": inv.get("Width"), "height": inv.get("Height"), "installed": len(slots),
                    "broken": sum(1 for s in slots if s["broken"]),
                    "supercharged": len(super_xy), "supercharged_good": len(good),
                    "supercharged_weak": [s["name"] for s in weak], "supercharged_empty": len(empty),
                    "move_in": [f"{s['class'] or '?'}-class {short(s['name'])}" for s in moves],
                    "move_out": [s["name"] for s in weak][:len(moves)],
                    "upgrade": [f"{s['class'] or '?'}-class {short(s['name'])}" for s in upgrades[:3]],
                    "isolated": isolated, "slots": slots}

        out = []
        for key, label in (("Inventory_TechOnly", "Exosuit"), ("Inventory", "Exosuit general")):
            r = review(ps.get(key, {}), label, True)
            if r:
                out.append(r)
        for i, mt in enumerate(ps.get("Multitools", [])):
            r = review(mt.get("Store", {}), f"Multi-tool {i + 1}" + (f": {mt['Name']}" if mt.get("Name") else ""),
                       i == ps.get("ActiveMultioolIndex"))
            if r:
                out.append(r)
        for i, sh in enumerate(ps.get("ShipOwnership", [])):
            r = review(sh.get("Inventory_TechOnly", {}), f"Ship {i + 1}: {sh.get('Name') or 'unnamed'}", i == ps.get("PrimaryShip"))
            if r:
                out.append(r)
        r = review(ps.get("FreighterInventory_TechOnly", {}), f"Freighter {ps.get('PlayerFreighterName') or ''}".strip(), True)
        if r:
            out.append(r)
        for i, v in enumerate(ps.get("VehicleOwnership", [])):
            kind = VEHICLE_NAMES[i] if i < len(VEHICLE_NAMES) else f"Exocraft {i + 1}"
            r = review(v.get("Inventory_TechOnly", {}), f"{kind}" + (f": {v['Name']}" if v.get("Name") else ""),
                       i == ps.get("PrimaryVehicle"))
            if r:
                out.append(r)
        return out

    def _tidy(self, ps: dict, name) -> dict:
        """Every stack in the tidied containers against data/nms_storage_plan.json:
        what has to move where, what is doubled up, and whether each container
        has the slots for what is coming."""
        try:
            with open(STORAGE_PLAN) as fh:
                plan = json.load(fh)
        except (OSError, ValueError) as e:
            return {"enabled": False, "error": f"{STORAGE_PLAN}: {e}"}
        items = self.tables.get("items", {})
        containers = plan.get("containers") or []
        labels = {c["container"]: c.get("label") or "" for c in containers}
        tidy = [c for c in (plan.get("tidy") or [c["container"] for c in containers])]
        default = plan.get("default") or (containers[-1]["container"] if containers else None)
        rules = [(c["container"], set(c.get("ids") or []), [re.compile(p) for p in c.get("patterns") or []],
                  set(c.get("categories") or [])) for c in containers]

        def target(iid: str) -> str | None:
            base = iid.split("#", 1)[0]
            for cont, ids, pats, _ in rules:
                if base in ids or any(p.search(base) for p in pats):
                    return cont
            cat = items.get(base, {}).get("category")
            for cont, _, _, cats in rules:
                if cat and cat in cats:
                    return cont
            return default

        key_for = {label: key for key, label in CONTAINER_KEYS}
        moves, after, capacity, stacks_now = [], {}, {}, {}
        for cont in tidy:
            inv = ps.get(key_for.get(cont, ""), {})
            capacity[cont] = len(inv.get("ValidSlotIndices") or []) or (inv.get("Width") or 0) * (inv.get("Height") or 0)
            stacks_now[cont] = 0
            for sl in inv.get("Slots", []) if isinstance(inv, dict) else []:
                if sl.get("Type", {}).get("InventoryType") not in ("Product", "Substance"):
                    continue
                stacks_now[cont] += 1
                iid = (sl.get("Id") or "").lstrip("^")
                to = target(iid)
                if to not in tidy:
                    to = cont                      # nowhere planned for it: it stays
                rec = after.setdefault(to, {}).setdefault(iid, {"item": name(iid), "amount": 0, "max": 0, "stacks_here": 0})
                rec["amount"] += sl.get("Amount") or 0
                rec["max"] = max(rec["max"], sl.get("MaxAmount") or 0)
                if to == cont:
                    rec["stacks_here"] += 1
                else:
                    moves.append({"id": iid, "item": name(iid), "amount": sl.get("Amount") or 0, "from": cont, "to": to,
                                  "to_label": labels.get(to, "")})
        summary = []
        merges = 0
        for cont in tidy:
            recs = after.get(cont, {})
            need = sum(max(1, math.ceil(r["amount"] / r["max"])) if r["max"] else 1 for r in recs.values())
            dup = sum(max(0, r["stacks_here"] - max(1, math.ceil(r["amount"] / r["max"]) if r["max"] else 1)) for r in recs.values())
            merges += dup
            incoming = [m for m in moves if m["to"] == cont]
            summary.append({"container": cont, "label": labels.get(cont, ""), "stacks_now": stacks_now.get(cont, 0),
                            "stacks_after": need, "capacity": capacity.get(cont, 0), "incoming": len(incoming),
                            "outgoing": sum(1 for m in moves if m["from"] == cont), "merges": dup,
                            "over_capacity": max(0, need - capacity.get(cont, 0))})
        order = {c: i for i, c in enumerate(tidy)}
        moves.sort(key=lambda m: (order.get(m["to"], 99), -m["amount"]))
        return {"enabled": True, "plan": STORAGE_PLAN, "moves": moves, "merges": merges, "containers": summary}

    # -- projection (per request) ----------------------------------------------
    def projected(self, now: float | None = None) -> dict:
        """Snapshot plus time-dependent fields, evaluated at `now`."""
        now = now or time.time()
        snap = json.loads(json.dumps(self.snapshot, default=list))   # cheap deep copy
        if "save" not in snap or not snap["save"]:
            return snap
        snap["now"] = now
        snap["save"]["age"] = now - snap["save"]["mtime"]
        ext = self.tables.get("extraction", {})
        upi = ext.get("resource_units_per_item", 1440)
        for r in snap["refiners"]:
            spo = r["seconds_per_op"] or 1
            elapsed = max(0.0, now - r["last_update"])
            # The output slot caps at the item's stack size (9999 for substances,
            # 10 for most products); the refiner stalls there with inputs left.
            ops = r["ops_remaining"]
            if r["output_cap"] and r["output_per_op"]:
                ops_to_cap = max(0, (r["output_cap"] - r["output_amount"]) // r["output_per_op"])
                r["stalls_at_cap"] = ops_to_cap < ops
                ops = min(ops, ops_to_cap)
            else:
                r["stalls_at_cap"] = False
            done = min(ops, int(elapsed // spo))
            r["projected_ops_done"] = done
            r["projected_output"] = r["output_amount"] + done * r["output_per_op"]
            if r["output_cap"]:
                r["projected_output"] = min(r["projected_output"], r["output_cap"])
            r["projected_inputs"] = [max(0, i["amount"] - done * i["per_op"]) for i in r["inputs"]]
            r["remaining_seconds"] = max(0.0, ops * spo - elapsed)
            r["finish_at"] = r["last_update"] + ops * spo
            r["progress"] = 1.0 if ops == 0 else min(1.0, done / ops)
            r["active"] = 1 if ops and r["remaining_seconds"] > 0 else 0
        for f in snap["farms"].values():
            elapsed = max(0.0, now - f["anchor"])
            proj = min(f["capacity_units"], f["stored_units"] + f["rate_units_per_s"] * elapsed)
            f["projected_units"] = proj
            f["projected_items"] = proj / upi
            f["fill_ratio"] = proj / f["capacity_units"] if f["capacity_units"] else 0
            f["full_in_seconds"] = ((f["capacity_units"] - proj) / f["rate_units_per_s"]) if f["rate_units_per_s"] > 0 else None
        for rec in snap["plants"].values():
            mature = 0
            for pl in rec["plants"]:
                g = min(pl["grow_seconds"], pl["grown"] + max(0.0, now - pl["anchor"]))
                pl["projected_grown"] = g
                pl["ready_in_seconds"] = max(0.0, pl["grow_seconds"] - g)
                mature += 1 if g >= pl["grow_seconds"] else 0
            rec["total"], rec["mature"] = len(rec["plants"]), mature
        for e in snap["fleet"].get("expeditions", []):
            e["remaining_seconds"] = max(0.0, e["eta"] - now)
            e["progress"] = min(1.0, (now - e["start"]) / (e["events"] * e["event_seconds"])) if e["events"] else 1.0
            e["returned"] = 1 if e["remaining_seconds"] == 0 else 0
        return snap

    # -- exposition -------------------------------------------------------------
    def metrics(self, now: float | None = None) -> str:
        now = now or time.time()
        snap = self.projected(now)
        L: list[str] = []

        def esc(v) -> str:
            # Procedural item ids carry raw bytes, some of which are line breaks
            # to a text parser; anything unprintable becomes a placeholder.
            text = "".join(ch if ch.isprintable() else "?" for ch in str(v))
            return text.replace("\\", "\\\\").replace('"', '\\"')

        def m(name_: str, help_: str, kind: str, rows):
            L.append(f"# HELP {name_} {help_}")
            L.append(f"# TYPE {name_} {kind}")
            for labels, value in rows:
                if value is None:
                    continue
                lab = ",".join(f'{k}="{esc(v)}"' for k, v in labels.items())
                L.append(f"{name_}{{{lab}}} {value}" if lab else f"{name_} {value}")

        ok = 1 if snap.get("save") and not snap.get("errors", {}).get("save") else 0
        m("nms_collector_up", "Save decoded and metrics current (1) or not (0).", "gauge", [({}, ok)])
        m("nms_collector_decodes_total", "Save files decoded since start.", "counter", [({}, self.decodes)])
        m("nms_collector_decode_failures_total", "Save files that failed to decode.", "counter", [({}, self.decode_failures)])
        m("nms_collector_decode_duration_seconds", "Time to decode the last save.", "gauge", [({}, round(self.decode_seconds, 3))])
        if not ok:
            return "\n".join(L) + "\n"

        s, p, u = snap["save"], snap["player"], snap["universe"]
        m("nms_save_info", "Which save is being read.", "gauge",
          [({"file": s["file"], "summary": s["summary"], "version": s["version"], "platform": s["platform"],
             "mode": s["game_mode"], "difficulty": s["difficulty"], "context": s["context"]}, 1)])
        m("nms_save_mtime_seconds", "Unix time the save file was written.", "gauge", [({}, int(s["mtime"]))])
        m("nms_save_timestamp_seconds", "Unix time the game stamped inside the save.", "gauge", [({}, s["timestamp"])])
        m("nms_save_age_seconds", "Seconds since the save file was written (projection horizon).", "gauge", [({}, int(s["age"]))])
        m("nms_units", "Units (credits).", "gauge", [({}, p["units"])])
        m("nms_nanites", "Nanites.", "gauge", [({}, p["nanites"])])
        m("nms_quicksilver", "Quicksilver.", "gauge", [({}, p["quicksilver"])])
        m("nms_health", "Player health.", "gauge", [({}, p["health"])])
        m("nms_shield", "Player shield.", "gauge", [({}, p["shield"])])
        m("nms_life_support", "Life support energy.", "gauge", [({}, p["energy"])])
        m("nms_ship_health", "Current ship health.", "gauge", [({}, p["ship_health"])])
        m("nms_time_alive_seconds", "Seconds alive in the current life.", "gauge", [({}, p["time_alive"])])
        m("nms_play_time_seconds", "Total play time on this save.", "counter", [({}, p["total_play_time"])])
        m("nms_ammo", "Ammunition loaded per weapon.", "gauge", [({"weapon": k}, v) for k, v in p["ammo"].items()])
        m("nms_universe_address", "Current galactic address components.", "gauge",
          [({"axis": k}, v) for k, v in u.items() if isinstance(v, (int, float)) and not isinstance(v, bool)])
        m("nms_collection_count", "How many of each thing the player has.", "gauge",
          [({"kind": k}, v) for k, v in snap["collections"].items()])
        m("nms_stat", "Lifetime counters from the save's GLOBAL_STATS block.", "gauge",
          [({"stat": k}, v) for k, v in sorted(snap["stats"].items())])

        m("nms_item_total", "Total of an item across every container.", "gauge",
          [({"item": r["item"], "id": iid, "type": r["type"]}, r["total"]) for iid, r in sorted(snap["items"].items())])
        m("nms_item_stacks", "Number of stacks an item is split into.", "gauge",
          [({"item": r["item"], "id": iid, "type": r["type"]}, r["stacks"]) for iid, r in sorted(snap["items"].items())])
        agg: dict = {}
        for l in snap["locations"]:
            k = (l["location"], l["id"], l["item"], l["type"])
            agg[k] = agg.get(k, 0) + l["amount"]
        m("nms_item_amount", "Amount of an item in one container.", "gauge",
          [({"location": k[0], "id": k[1], "item": k[2], "type": k[3]}, v) for k, v in sorted(agg.items())])

        rl = lambda r: {"refiner": r["key"], "base": r.get("base", ""), "recipe": r["recipe"], "output": r["output"]}
        R = snap["refiners"]
        m("nms_refiner_active", "Refiner has work left (projected).", "gauge", [(rl(r), r["active"]) for r in R])
        m("nms_refiner_progress_ratio", "Share of the loaded job done (projected).", "gauge", [(rl(r), round(r["progress"], 4)) for r in R])
        m("nms_refiner_remaining_seconds", "Seconds until the loaded inputs are exhausted (projected).", "gauge", [(rl(r), int(r["remaining_seconds"])) for r in R])
        m("nms_refiner_finish_timestamp_seconds", "Unix time the loaded job completes.", "gauge", [(rl(r), int(r["finish_at"])) for r in R])
        m("nms_refiner_output_amount", "Output stack size (projected).", "gauge", [(rl(r), r["projected_output"]) for r in R])
        m("nms_refiner_output_saved", "Output stack size as last saved.", "gauge", [(rl(r), r["output_amount"]) for r in R])
        m("nms_refiner_input_amount", "Input remaining (projected).", "gauge",
          [(dict(rl(r), input=i["item"]), v) for r in R for i, v in zip(r["inputs"], r["projected_inputs"])])
        m("nms_refiner_seconds_per_op", "Recipe time per operation.", "gauge", [(rl(r), r["seconds_per_op"]) for r in R])
        m("nms_refiner_last_update_seconds", "Unix time the refiner state was last written.", "gauge", [(rl(r), r["last_update"]) for r in R])

        F = list(snap["farms"].values())
        fl = lambda f: {"base": f["base"], "name": f["name"], "kind": f["kind"]}
        m("nms_farm_stored_items", "Items in the farm's extractors and depots (projected).", "gauge", [(fl(f), round(f["projected_items"], 1)) for f in F])
        m("nms_farm_stored_items_saved", "Items in the farm as last saved.", "gauge", [(fl(f), round(f["stored_items"], 1)) for f in F])
        m("nms_farm_capacity_items", "Total storage of the farm's extractors and depots.", "gauge", [(fl(f), round(f["capacity_items"], 1)) for f in F])
        m("nms_farm_fill_ratio", "Farm storage used (projected).", "gauge", [(fl(f), round(f["fill_ratio"], 4)) for f in F])
        m("nms_farm_rate_items_per_hour", "Extraction rate, measured from save history when possible.", "gauge", [(fl(f), round(f["rate_items_per_hour"], 2)) for f in F])
        m("nms_farm_rate_measured", "1 if the rate was measured from history, 0 if assumed class-C.", "gauge", [(fl(f), 1 if f["rate_measured"] else 0) for f in F])
        m("nms_farm_full_in_seconds", "Seconds until the farm's storage is full (projected).", "gauge", [(fl(f), int(f["full_in_seconds"])) for f in F if f["full_in_seconds"] is not None])
        m("nms_farm_extractors", "Extractors in the farm.", "gauge", [(fl(f), f["extractors"] + f["gas_extractors"]) for f in F])
        m("nms_farm_depots", "Supply depots in the farm.", "gauge", [(fl(f), f["depots"]) for f in F])
        m("nms_farm_anchor_seconds", "Unix time the farm's fill level was last written.", "gauge", [(fl(f), f["anchor"]) for f in F])

        P = list(snap["plants"].values())
        m("nms_plants_total", "Plants in a base.", "gauge", [({"base": r["base"]}, r["total"]) for r in P])
        m("nms_plants_mature", "Plants ready to harvest (projected).", "gauge", [({"base": r["base"]}, r["mature"]) for r in P])
        m("nms_plant_ready_in_seconds", "Seconds until each plant is harvestable (projected).", "gauge",
          [({"base": r["base"], "plant": pl["plant"], "index": str(i)}, int(pl["ready_in_seconds"])) for r in P for i, pl in enumerate(r["plants"])])

        fleet = snap["fleet"]
        m("nms_frigates", "Frigates in the fleet.", "gauge", [({"class": c}, n) for c, n in sorted(fleet["frigate_classes"].items())])
        E = fleet["expeditions"]
        el = lambda e: {"expedition": str(e["index"]), "category": e["category"], "duration": e["duration"]}
        m("nms_expedition_start_seconds", "Unix time the expedition departed.", "gauge", [(el(e), e["start"]) for e in E])
        m("nms_expedition_eta_seconds", "Unix time the expedition is due back.", "gauge", [(el(e), e["eta"]) for e in E])
        m("nms_expedition_remaining_seconds", "Seconds until the expedition returns (projected).", "gauge", [(el(e), int(e["remaining_seconds"])) for e in E])
        m("nms_expedition_progress_ratio", "Share of the voyage elapsed (projected).", "gauge", [(el(e), round(e["progress"], 4)) for e in E])
        m("nms_expedition_events", "Events in the expedition plan.", "gauge", [(el(e), e["events"]) for e in E])
        m("nms_expedition_events_done", "Events resolved so far (as saved).", "gauge", [(el(e), e["events_done"]) for e in E])
        m("nms_expedition_events_failed", "Events failed so far (as saved).", "gauge", [(el(e), e["events_failed"]) for e in E])
        m("nms_expedition_frigates", "Frigates on the expedition.", "gauge", [(el(e), e["frigates"]) for e in E])
        m("nms_expedition_frigates_damaged", "Frigates damaged on the expedition.", "gauge", [(el(e), e["damaged"]) for e in E])
        m("nms_expedition_frigates_destroyed", "Frigates destroyed on the expedition.", "gauge", [(el(e), e["destroyed"]) for e in E])
        m("nms_expedition_returned", "1 once the projected return time has passed.", "gauge", [(el(e), e["returned"]) for e in E])
        FR = fleet.get("roster") or []
        fl2 = lambda f: {"frigate": f["name"], "type": f["type"], "class": f["inventory_class"]}
        m("nms_frigate_score", "Base-roll score of a frigate: stats less traits and rank-ups, clamped to -5..14.", "gauge", [(fl2(f), f["score"]) for f in FR])
        m("nms_frigate_level", "Rank-ups a frigate has earned from expeditions.", "gauge", [(fl2(f), f["level"]) for f in FR])
        m("nms_frigate_stat", "A frigate's current stat.", "gauge",
          [(dict(fl2(f), stat=k), v) for f in FR for k, v in f["stats"].items()])
        m("nms_frigate_expeditions", "Expeditions a frigate has completed.", "gauge", [(fl2(f), f["expeditions"]) for f in FR])
        m("nms_frigate_info", "Race and traits, as labels; value = sum of the four main stats.", "gauge",
          [(dict(fl2(f), race=f["race"], traits=", ".join(f["traits"])), f["main_total"]) for f in FR])

        U = snap.get("universe") or {}
        m("nms_universe_info", "Where the save says you are: portal glyphs and galactic address.", "gauge",
          [({"glyphs": U.get("glyphs", ""), "address": U.get("address", ""), "galaxy": str(U.get("galaxy", "")),
             "system": str(U.get("system", "")), "planet": str(U.get("planet", ""))}, 1)])

        # plants by kind, with what they yield and how much of it is in stock
        kinds: dict = {}
        totals = snap.get("items") or {}
        for r in P:
            for pl in r["plants"]:
                k = kinds.setdefault((r["base"], pl["plant"]), {"base": r["base"], "plant": pl["plant"], "yields": pl.get("yields") or "",
                                                                 "yield_id": pl.get("yield_id") or "", "total": 0, "mature": 0, "waits": []})
                k["total"] += 1
                if pl["ready_in_seconds"] > 0:
                    k["waits"].append(pl["ready_in_seconds"])
                else:
                    k["mature"] += 1
        kl = lambda k: {"base": k["base"], "plant": k["plant"], "yields": k["yields"]}
        m("nms_plant_kind_total", "Plants of one kind in a base.", "gauge", [(kl(k), k["total"]) for k in kinds.values()])
        m("nms_plant_kind_mature", "Plants of one kind ready to harvest (projected).", "gauge", [(kl(k), k["mature"]) for k in kinds.values()])
        m("nms_plant_kind_next_ready_seconds", "Seconds until the next plant of this kind is ready; 0 when all are.", "gauge",
          [(kl(k), int(min(k["waits"])) if k["waits"] else 0) for k in kinds.values()])
        m("nms_plant_kind_stock", "How much of what this plant yields is in stock across every container.", "gauge",
          [(kl(k), (totals.get(k["yield_id"]) or {}).get("total", 0)) for k in kinds.values()])

        MS = snap.get("missions") or {}
        m("nms_missions", "Missions by status (hints, wiki pages and lore flags excluded).", "gauge",
          [({"status": k}, v) for k, v in (MS.get("counts") or {}).items()])
        m("nms_mission_remaining_steps", "Internal stages left in a mission that is in progress.", "gauge",
          [({"mission": r["id"], "title": r["title"]}, r["remaining"]) for r in MS.get("in_progress", []) if r["remaining"] is not None])
        m("nms_mission_info", "A mission in progress: current objective and what finishing it hands out. Value = stage reached (1-based).", "gauge",
          [({"mission": r["id"], "title": r["title"], "objective": r["objective"], "rewards": ", ".join(r["rewards"]),
             "selected": "1" if r["selected"] else "0"}, (r["progress"] or 0) + 1) for r in MS.get("in_progress", [])])
        m("nms_mission_stages", "Stages in a mission that is in progress.", "gauge",
          [({"mission": r["id"], "title": r["title"]}, r["final"]) for r in MS.get("in_progress", []) if r["final"] is not None])

        T = snap.get("tech") or []
        tl = lambda t: {"inventory": t["inventory"], "primary": "1" if t["primary"] else "0"}
        m("nms_tech_installed", "Technologies installed in an inventory.", "gauge", [(tl(t), t["installed"]) for t in T])
        m("nms_tech_supercharged", "Supercharged slots in an inventory.", "gauge", [(tl(t), t["supercharged"]) for t in T])
        m("nms_tech_supercharged_wasted", "Supercharged slots that are empty or hold a fixed technology instead of a module.", "gauge",
          [(tl(t), len(t["supercharged_weak"]) + t["supercharged_empty"]) for t in T])
        m("nms_tech_isolated", "Technologies not touching another of their stat family.", "gauge", [(tl(t), len(t["isolated"])) for t in T])
        m("nms_tech_supercharged_good", "Supercharged slots holding an upgrade module.", "gauge", [(tl(t), t["supercharged_good"]) for t in T])
        m("nms_tech_broken", "Damaged technology slots in an inventory.", "gauge", [(tl(t), t["broken"]) for t in T])
        m("nms_tech_info", "Inventory class, as a label.", "gauge", [(dict(tl(t), **{"class": t.get("class") or "?"}), 1) for t in T])
        m("nms_tech_move", "A module that should take a supercharged slot, and what it would displace.", "gauge",
          [(dict(tl(t), module=mv, instead_of=(t["move_out"][i] if i < len(t["move_out"]) else "")), 1)
           for t in T for i, mv in enumerate(t["move_in"])])
        iso_fam: dict = {}
        for t in T:
            for i in t["isolated"]:
                key = (t["inventory"], i.get("family_name", i["family"]))
                iso_fam[key] = iso_fam.get(key, 0) + 1
        m("nms_tech_isolated_family", "Members of a stat family not touching another member, per inventory and family.", "gauge",
          [({"inventory": inv, "family": fam}, n) for (inv, fam), n in iso_fam.items()])

        TD = snap.get("tidy") or {}
        if TD.get("enabled"):
            m("nms_tidy_moves", "Stacks sitting in a container other than the one the storage plan gives them.", "gauge", [({}, len(TD["moves"]))])
            m("nms_tidy_merges", "Extra stacks that would merge once everything is in its planned container.", "gauge", [({}, TD["merges"])])
            m("nms_tidy_stacks_after", "Slots a container needs once the plan is applied.", "gauge",
              [({"container": c["container"], "label": c["label"]}, c["stacks_after"]) for c in TD["containers"]])
            m("nms_tidy_capacity", "Slots a container has.", "gauge",
              [({"container": c["container"], "label": c["label"]}, c["capacity"]) for c in TD["containers"]])
            m("nms_tidy_stacks_now", "Stacks a container holds now.", "gauge",
              [({"container": c["container"], "label": c["label"]}, c["stacks_now"]) for c in TD["containers"]])
            m("nms_tidy_incoming", "Stacks the plan brings into a container.", "gauge",
              [({"container": c["container"], "label": c["label"]}, c["incoming"]) for c in TD["containers"]])
            m("nms_tidy_outgoing", "Stacks the plan takes out of a container.", "gauge",
              [({"container": c["container"], "label": c["label"]}, c["outgoing"]) for c in TD["containers"]])
            m("nms_tidy_move", "One stack to move: amount, from, to.", "gauge",
              [({"item": mv["item"], "from": mv["from"], "to": mv["to"], "label": mv.get("to_label", "")}, mv["amount"]) for mv in TD["moves"]])

        C = self.crafting_result
        nm = self.crafting.name
        m("nms_crafting_compute_seconds", "Time the last crafting evaluation took.", "gauge", [({}, round(self.crafting_seconds, 2))])
        il = lambda c: {"item": c["item"], "id": c["id"], "known": "1" if c["known"] else "0"}
        m("nms_craftable", "Units makeable now from stock, crafting missing intermediates via known routes.", "gauge",
          [(dict(il(c), route=c["best_route"] or "none", recipe=c["best_recipe"] or "none"), c["makeable"]) for c in C.values()])
        m("nms_craftable_direct", "Units makeable now from stock alone, per route (one level).", "gauge",
          [(dict(il(c), route=r["route"], recipe=r["recipe"], recipe_id=r["recipe_id"], recipe_known="1" if r["known"] else "0"), r["direct"])
           for c in C.values() for r in c["routes"]])
        m("nms_recipe_yield", "Units produced per craft or refiner operation.", "gauge",
          [(dict(il(c), route=r["route"], recipe=r["recipe"], recipe_id=r["recipe_id"], recipe_known="1" if r["known"] else "0"), r["yield"])
           for c in C.values() for r in c["routes"]])
        m("nms_recipe_need", "Ingredient amount per craft or refiner operation.", "gauge",
          [(dict(il(c), route=r["route"], recipe=r["recipe"], recipe_id=r["recipe_id"], recipe_known="1" if r["known"] else "0",
                 ingredient=nm(ing), ingredient_id=ing), amt)
           for c in C.values() for r in c["routes"] for ing, amt in r["needs"]])
        m("nms_craft_raw_need", "Raw materials per unit with every intermediate expanded through the best known route.", "gauge",
          [(dict(il(c), ingredient=nm(ing), ingredient_id=ing), amt) for c in C.values() for ing, amt in c["raw_need"].items()])
        CS = snap.get("crafting") or {}
        m("nms_craft_blocked_by", "Known blueprints that cannot be made because of this ingredient.", "gauge",
          [({"ingredient": g["ingredient"], "ingredient_id": g["id"]}, len(g["items"])) for g in CS.get("by_ingredient", [])])
        m("nms_craft_blocked_only_by", "Known blueprints for which this is the only missing ingredient.", "gauge",
          [({"ingredient": g["ingredient"], "ingredient_id": g["id"]}, sum(1 for i in g["items"] if i.get("only"))) for g in CS.get("by_ingredient", [])])
        m("nms_craft_blocked_have", "Stock of an ingredient that blocks known blueprints.", "gauge",
          [({"ingredient": g["ingredient"], "ingredient_id": g["id"]}, g["have"]) for g in CS.get("by_ingredient", [])])
        m("nms_craft_blocked_short", "Smallest shortfall of this ingredient among the blueprints it blocks.", "gauge",
          [({"ingredient": g["ingredient"], "ingredient_id": g["id"]}, min(i["short"] for i in g["items"])) for g in CS.get("by_ingredient", []) if g["items"]])
        m("nms_craft_shortfall", "Raw materials missing to make one unit now, using intermediates already in stock.", "gauge",
          [(dict(il(c), ingredient=nm(ing), ingredient_id=ing), amt) for c in C.values() for ing, amt in c["shortfall"].items()])
        return "\n".join(L) + "\n"
