"""Partial re-extraction from the MXMLs MBINCompiler 7.04.1-pre3 did convert, then diff against data/nms_tables.json."""
import importlib.util, json, sys, traceback
REPO = "/home/bob/Projects/nms-exporter"
WORK = "/tmp/nms-extract-20261103"
spec = importlib.util.spec_from_file_location("ext", REPO + "/scripts/nms-extract-tables.py")
ext = importlib.util.module_from_spec(spec); spec.loader.exec_module(ext)
old = json.load(open(REPO + "/data/nms_tables.json"))
new = {"meta": {"game_build_id": ext.game_build(), "partial": True,
                "note": "built from the MXMLs MBINCompiler 7.04.1-pre3 converted; GUID-matched templates only unless marked suspect"}}
status = {}
def attempt(name, fn):
    try:
        new[name] = fn(); status[name] = "ok"
    except Exception as e:
        status[name] = "FAILED: %s: %s" % (type(e).__name__, e)
loc = ext.parse_loc(WORK)
attempt("recipes", lambda: ext.parse_recipes(WORK, loc, {}, old["refiner"]["made_in_time"]))
attempt("fleet", lambda: ext.parse_fleet(WORK, loc))
attempt("hotspots", lambda: ext.parse_hotspots(WORK))
attempt("biomes_by_star", lambda: ext.parse_star_biomes(WORK))
attempt("labels", lambda: ext.parse_biome_labels(loc))
attempt("globals_SUSPECT", lambda: ext.parse_globals(WORK))
attempt("items_SUSPECT", lambda: ext.parse_items(WORK, loc))
new["status"] = status
json.dump(new, open("/tmp/nms_tables_new.json", "w"), indent=1, default=str)
print(json.dumps(status, indent=1))
print("loc strings", len(loc))
