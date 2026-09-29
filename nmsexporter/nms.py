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
import os
import threading
import time
import urllib.request

from . import nmssave

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

# --- configuration (env overrides) -------------------------------------------
_HOMES = [os.path.expanduser("~")] + sorted(glob.glob("/home/*"))
_SAVE_GLOB = "/.local/share/Steam/steamapps/compatdata/275850/pfx/drive_c/users/steamuser/AppData/Roaming/HelloGames/NMS/st_*"
SAVE_DIR = os.environ.get("NMS_SAVE_DIR", "")
TABLES = os.environ.get("NMS_TABLES", os.path.join(ROOT, "data", "nms_tables.json"))
_state_root = os.environ.get("STATE_DIRECTORY") or os.path.expanduser("~/.cache/nms-exporter")
_cache_root = os.environ.get("CACHE_DIRECTORY") or _state_root
STATE_FILE = os.environ.get("NMS_STATE", os.path.join(_state_root, "nms_state.json"))
MAPPING_CANDIDATES = [os.environ.get("NMS_MAPPING", ""),
                      os.path.join(_cache_root, "mapping.json"),
                      os.path.join(ROOT, "data", "nms_mapping.json")]

RESOURCE_KINDS = {"^U_EXTRACTOR_S": "mineral", "^U_GASEXTRACTOR": "gas", "^U_SILO_S": "depot"}
EXTRACTORS = {"^U_EXTRACTOR_S", "^U_GASEXTRACTOR"}
SUBSTANCE_STACK = 9999          # refiner output cap for substances
REFINER_STALE_SECONDS = 7 * 86400   # ignore refiner entries not touched for a week
PLANT_NAMES = {"RADIOPLANT": "Gamma Weed", "TOXICPLANT": "Fungal Cluster", "SNOWPLANT": "Frostwort",
               "SACVENOMPLANT": "Venom Urchin", "SCORCHEDPLANT": "Solar Vine", "POOPPLANT": "Coprite Sphere",
               "GRAVPLANT": "Gravitino Host", "CREATUREPLANT": "Mordite Root", "BARRENPLANT": "Echinocactus",
               "LUSHPLANT": "Star Bramble", "PEARLPLANT": "Albumen Pearl Orb", "NIPPLANT": "NipNip Buds"}
GAME_MODES = {1: "Normal", 2: "Creative", 3: "Survival", 4: "Permadeath", 5: "Ambient"}

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
            return {"errors": str(e), "items": {}, "recipes": [], "buildings": {}, "fleet": {}, "extraction": {}}

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
            self._save_state()

    # -- snapshot (static part, computed once per save) ----------------------
    def _build(self, save: dict, path: str, mtime: float) -> dict:
        ps = save["BaseContext"]["PlayerStateData"]
        common = save.get("CommonStateData", {})
        items = self.tables.get("items", {})

        def name(iid: str) -> str:
            return items.get(iid.lstrip("^"), {}).get("name") or iid.lstrip("^")

        def itype(iid: str) -> str:
            return items.get(iid.lstrip("^"), {}).get("type") or "Unknown"

        snap = {"errors": {}, "save": {}, "player": {}, "stats": {}, "collections": {},
                "items": {}, "locations": [], "refiners": [], "farms": {}, "plants": {},
                "fleet": {}, "universe": {}}
        s = snap["save"]
        s.update(path=path, file=os.path.basename(path), mtime=mtime, timestamp=ps.get("TimeStamp", 0),
                 summary=ps.get("SaveSummary", ""), version=save.get("Version"), platform=save.get("Platform"),
                 game_mode=GAME_MODES.get(save["BaseContext"].get("GameMode"), str(save["BaseContext"].get("GameMode"))),
                 context=save.get("ActiveContext"),
                 difficulty=ps.get("DifficultyState", {}).get("Preset", {}).get("DifficultyPresetType"),
                 save_name=common.get("SaveName") or "")

        p = snap["player"]
        p.update(units=ps.get("Units"), nanites=ps.get("Nanites"), quicksilver=ps.get("Specials"),
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

        # lifetime counters
        for g in ps.get("Stats", []):
            if g.get("GroupId") == "^GLOBAL_STATS":
                for st in g.get("Stats", []):
                    v = _stat_value(st.get("Value"))
                    if v is not None:
                        snap["stats"][st["Id"].lstrip("^")] = v

        dd = save.get("DiscoveryManagerData", {}).get("DiscoveryData-v1", {})
        snap["collections"] = dict(
            ships=sum(1 for x in ps.get("ShipOwnership", []) if x.get("Name") or x.get("Inventory", {}).get("Slots")),
            multitools=len(ps.get("Multitools", [])), pets=len(ps.get("Pets", [])), eggs=len(ps.get("Eggs", [])),
            frigates=len(ps.get("FleetFrigates", [])), bases=len(ps.get("PersistentPlayerBases", [])),
            visited_systems=len(ps.get("VisitedSystems", [])), known_tech=len(ps.get("KnownTech", [])),
            known_products=len(ps.get("KnownProducts", [])), known_recipes=len(ps.get("KnownRefinerRecipes", [])),
            known_words=len(ps.get("KnownWords", [])), discoveries=len(dd.get("Store", {}).get("Record", [])),
            vehicles=len(ps.get("VehicleOwnership", [])), settlements=sum(1 for x in ps.get("SettlementStatesV2", []) if x.get("Name")))

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
                             frigate_classes={},)
        for f in fr:
            c = f.get("FrigateClass", {}).get("FrigateClass", "?")
            snap["fleet"]["frigate_classes"][c] = snap["fleet"]["frigate_classes"].get(c, 0) + 1
        return snap

    def _refiners(self, ps: dict, name, itype) -> list:
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
                recipe=r["operation"], recipe_id=r["id"], seconds_per_op=r["seconds_per_op"],
                output_id=out_id, output=name(out_id), output_amount=max(0, out_slot["Amount"]),
                output_per_op=r["result"]["amount"],
                output_cap=SUBSTANCE_STACK if itype(out_id) == "Substance" else (out_slot.get("MaxAmount") or 0),
                inputs=inputs, ops_remaining=ops or 0,
                last_update=d.get("LastUpdateTimestamp", 0), last_completed=d.get("LastCompletedTimestamp", 0)))
        return out

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
            bname = b.get("Name") or b.get("BaseType", {}).get("PersistentBaseTypes", "base")
            objs = b.get("Objects", [])
            res = [o for o in objs if o.get("ObjectID") in RESOURCE_KINDS]
            if res:
                f = farms.setdefault(bname, {"base": bname, "extractors": 0, "gas_extractors": 0, "depots": 0,
                                            "stored_units": 0, "capacity_units": 0, "anchor": b.get("LastUpdateTimestamp", 0)})
                for o in res:
                    oid = o["ObjectID"]
                    f["extractors" if oid == "^U_EXTRACTOR_S" else "gas_extractors" if oid == "^U_GASEXTRACTOR" else "depots"] += 1
                    f["stored_units"] += (o.get("UserData", 0) >> 32)
                    f["capacity_units"] += cap_units[oid]
                    f["anchor"] = max(f["anchor"], o.get("Timestamp", 0))
                f["kind"] = "gas" if f["gas_extractors"] and not f["extractors"] else "mineral"
                f["stored_items"] = f["stored_units"] / upi
                f["capacity_items"] = f["capacity_units"] / upi
            pl = [o for o in objs if o.get("ObjectID") in plant_grow]
            if pl:
                rec = plants.setdefault(bname, {"base": bname, "plants": []})
                for o in pl:
                    pid = o["ObjectID"].lstrip("^")
                    rec["plants"].append({"plant": PLANT_NAMES.get(pid, pid), "id": pid,
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

    # -- projection (per request) ----------------------------------------------
    def projected(self, now: float | None = None) -> dict:
        """Snapshot plus time-dependent fields, evaluated at `now`."""
        now = now or time.time()
        snap = json.loads(json.dumps(self.snapshot))   # cheap deep copy
        if "save" not in snap or not snap["save"]:
            return snap
        snap["now"] = now
        snap["save"]["age"] = now - snap["save"]["mtime"]
        ext = self.tables.get("extraction", {})
        upi = ext.get("resource_units_per_item", 1440)
        for r in snap["refiners"]:
            spo = r["seconds_per_op"] or 1
            elapsed = max(0.0, now - r["last_update"])
            done = min(r["ops_remaining"], int(elapsed // spo))
            r["projected_ops_done"] = done
            r["projected_output"] = r["output_amount"] + done * r["output_per_op"]
            if r["output_cap"]:
                r["projected_output"] = min(r["projected_output"], r["output_cap"])
            r["projected_inputs"] = [max(0, i["amount"] - done * i["per_op"]) for i in r["inputs"]]
            r["remaining_seconds"] = max(0.0, r["ops_remaining"] * spo - elapsed)
            r["finish_at"] = r["last_update"] + r["ops_remaining"] * spo
            r["progress"] = 1.0 if r["ops_remaining"] == 0 else min(1.0, done / r["ops_remaining"])
            r["active"] = 1 if r["ops_remaining"] and r["remaining_seconds"] > 0 else 0
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
            return str(v).replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ")

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
          [({"axis": k}, v) for k, v in u.items()])
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

        rl = lambda r: {"refiner": r["key"], "recipe": r["recipe"], "output": r["output"]}
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
        fl = lambda f: {"base": f["base"], "kind": f["kind"]}
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
        return "\n".join(L) + "\n"
