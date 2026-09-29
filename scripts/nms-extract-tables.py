#!/usr/bin/env python3
"""Build data/nms_tables.json from the installed No Man's Sky game files.

Pulls the refiner/cooking recipe table, item names, extractor and hotspot
constants, and the power/plant rates straight out of the game's .pak archives,
so the numbers always match the installed build rather than a wiki.

Needs two community tools (both single binaries, nothing to install):
  hgpaktool     https://github.com/monkeyman192/HGPAKtool/releases   (unpacks .pak)
  MBINCompiler  https://github.com/monkeyman192/MBINCompiler/releases (MBIN -> MXML)
MBINCompiler-linux needs a .NET 8 runtime; point DOTNET_ROOT at one if it is
not system-wide (dotnet-install.sh --runtime dotnet --channel 8.0 works).

Usage:
  scripts/nms-extract-tables.py [--pcbanks DIR] [--work DIR] [--out FILE]
                                [--hgpaktool BIN] [--mbincompiler BIN]
Re-run after every game update. Only the JSON output is used at runtime.
"""
import argparse, datetime, glob, json, os, re, subprocess, sys
import xml.etree.ElementTree as ET

STEAM = os.path.expanduser("~/.local/share/Steam/steamapps")
DEFAULT_PCBANKS = os.path.join(STEAM, "common/No Man's Sky/GAMEDATA/PCBANKS")
PAKS = ["NMSARC.MetadataEtc.pak", "NMSARC.globals.pak", "NMSARC.misc.pak", "NMSARC.Precache.pak"]
FILTERS = ["*GCRECIPETABLE*", "*GCSUBSTANCETABLE*", "*GCPRODUCTTABLE*", "*GCTECHNOLOGYTABLE*",
           "LANGUAGE/NMS_*_ENGLISH.MBIN", "*GCGAMEPLAYGLOBALS*", "*GCENVIRONMENTGLOBALS*",
           "*REGIONHOTSPOTSTABLE*", "*BASEBUILDINGOBJECTSTABLE*", "*GCFLEETGLOBALS*",
           "*NMS_BASEPARTPRODUCTS*", "*NMS_MODULARCUSTOMISATIONPRODUCTS*", "*PROCEDURALPRODUCTTABLE*"]
MAPPING_URL = "https://github.com/monkeyman192/MBINCompiler/releases/latest/download/mapping.json"


def run(cmd, **kw):
    r = subprocess.run(cmd, capture_output=True, text=True, **kw)
    if r.returncode != 0:
        sys.exit(f"command failed: {' '.join(cmd)}\n{r.stdout}\n{r.stderr}")
    return r.stdout


def find(work, pattern):
    hits = [p for p in glob.glob(os.path.join(work, "**", "*"), recursive=True)
            if re.search(pattern, os.path.basename(p), re.I)]
    return sorted(hits)


def extract(args):
    """Unpack the MBINs we need (if missing) and convert them to MXML (if missing)."""
    paks = [os.path.join(args.pcbanks, p) for p in PAKS]
    cmd = [args.hgpaktool, "-U", "-O", args.work]
    for f in FILTERS:
        cmd += ["-f", f]
    run(cmd + paks)          # fast (<1 s); re-unpacking keeps the MBINs current
    mbins = [p for p in find(args.work, r"\.mbin$") if "usenglish" not in p.lower()]
    todo = [p for p in mbins if not os.path.exists(p[:-5] + ".MXML")
            or os.path.getmtime(p) > os.path.getmtime(p[:-5] + ".MXML")]
    if todo:
        env = dict(os.environ)
        env.setdefault("DOTNET_ROOT", "/tmp/dotnet8")
        run([args.mbincompiler, "convert", "-y", "--force", "-q"] + todo, env=env)


# --- MXML helpers -----------------------------------------------------------
def props(el):
    return {p.get("name"): p for p in el.findall("Property")}


def val(el, name, default=None):
    p = props(el).get(name)
    return p.get("value") if p is not None else default


def num(s):
    f = float(s)
    return int(f) if f.is_integer() else f


def load(work, pattern):
    path = find(work, pattern)
    if not path:
        sys.exit(f"missing {pattern} under {work}")
    return ET.parse(path[0]).getroot()


# --- parsers -----------------------------------------------------------------
def parse_loc(work):
    loc = {}
    for path in find(work, r"^nms_.*_english\.mxml$"):
        for e in ET.parse(path).getroot().iter("Property"):
            if e.get("value") == "TkLocalisationEntry":
                pp = props(e)
                if "English" in pp:
                    loc[pp["Id"].get("value")] = pp["English"].get("value")
    return loc


def parse_items(work, loc):
    items = {}
    # base parts, corvette/modular parts and procedural items are GcProductData too, in their own tables
    for pat, tag, kind in [(r"gcsubstancetable\.mxml$", "GcRealitySubstanceData", "Substance"),
                           (r"gcproducttable\.mxml$", "GcProductData", "Product"),
                           (r"^nms_basepartproducts\.mxml$", "GcProductData", "Product"),
                           (r"^nms_modularcustomisationproducts\.mxml$", "GcProductData", "Product"),
                           (r"^proceduralproducttable\.mxml$", "GcProductData", "Product"),
                           (r"gctechnologytable\.mxml$", "GcTechnology", "Technology")]:
        for e in load(work, pat).iter("Property"):
            if e.get("value") == tag and val(e, "ID"):
                iid = val(e, "ID")
                key = val(e, "NameLower") or val(e, "Name")
                name = loc.get(key, key)
                if not name or "%" in name or name == key:   # procedural name templates: fall back to the subtitle
                    name = loc.get(val(e, "Subtitle"), name)
                rec = {"name": name, "type": kind}
                req = props(e).get("Requirements")
                if kind == "Product" and req is not None and val(e, "IsCraftable") == "true":
                    ings = [{"id": val(r, "ID"), "type": val(props(r)["Type"], "InventoryType"), "amount": int(val(r, "Amount"))}
                            for r in req.findall("Property")]
                    if ings:
                        rec["craft"] = {"ingredients": ings, "yield": int(val(e, "CraftAmountMultiplier") or 1)}
                sym = val(e, "Symbol")
                if sym and loc.get(sym):
                    rec["symbol"] = loc[sym]
                items[iid] = rec
    return items


def parse_recipes(work, loc, items, made_in_time):
    table = load(work, r"gcrecipetable\.mxml$").find("Property[@name='Table']")
    out = []
    for e in table.findall("Property"):
        pp = props(e)
        res = pp["Result"]

        def elem(x):
            return {"id": val(x, "Id"), "type": val(props(x)["Type"], "InventoryType"), "amount": int(val(x, "Amount"))}

        result = elem(res)
        cooking = val(e, "Cooking") == "true"
        t = float(val(e, "TimeToMake"))
        divisor = made_in_time["substance" if result["type"] == "Substance" else "product"]
        op = loc.get(val(e, "RecipeType"), val(e, "RecipeType"))
        out.append({
            "id": val(e, "Id"),
            "operation": re.sub(r"^Requested Operation:\s*", "", op or ""),
            "name": loc.get(val(e, "RecipeName"), None),
            "cooking": cooking,
            "time_to_make": num(t),
            "seconds_per_op": round(t / divisor, 6),
            "seconds_per_op_survival": round(t / made_in_time["survival_" + ("substance" if result["type"] == "Substance" else "product")], 6),
            "result": result,
            "ingredients": [elem(i) for i in pp["Ingredients"].findall("Property")],
        })
    return out


def parse_globals(work):
    g = load(work, r"gcgameplayglobals\.global\.mxml$")
    env = load(work, r"gcenvironmentglobals\.global\.mxml$")
    return {
        "substance": num(val(g, "RefinerSubsMadeInTime")),
        "product": num(val(g, "RefinerProductsMadeInTime")),
        "survival_substance": num(val(g, "RefinerSubsMadeInTimeSurvival")),
        "survival_product": num(val(g, "RefinerProductsMadeInTimeSurvival")),
    }, {
        "max_hotspot_offset_distance_m": num(val(env, "MaxHotspotOffsetDistance")),
        "min_hotspot_falloff_distance_m": num(val(env, "MinHotspotFalloffDistance")),
        "max_hotspot_falloff_distance_m": num(val(env, "MaxHotspotFalloffDistance")),
    }


def parse_fleet(work):
    g = load(work, r"gcfleetglobals\.global\.mxml$")
    durations = {d.get("name"): num(d.get("value"))
                 for d in props(props(g)["ExpeditionDurations"])["Duration"].findall("Property")}
    return {
        "event_seconds": num(val(g, "TimeTakenForExpeditionEvent")),
        "event_seconds_easy": num(val(g, "TimeTakenForExpeditionEvent_Easy")),
        "events_by_duration": durations,
        "passive_income_tick_seconds": num(val(g, "TimeBetweenPassiveIncomeTicks")),
    }


def parse_hotspots(work):
    root = load(work, r"regionhotspotstable\.mxml$")
    classes, biome_gases, substances = {}, {}, []
    for h in root.find("Property[@name='RegionHotspots']").findall("Property"):
        classes[h.get("name")] = {
            "class_weighting": {c.get("name"): num(c.get("value")) for c in props(h)["ClassWeightings"].findall("Property")},
            "class_strength": {c.get("name"): num(c.get("value")) for c in props(h)["ClassStrengths"].findall("Property")},
            "range_m": [num(val(h, "MinRange")), num(val(h, "MaxRange"))],
        }
    for b in root.find("Property[@name='RegionHotspotBiomeGases']").findall("Property"):
        if val(b, "Gas1Id"):
            biome_gases[b.get("name")] = {"gas1": val(b, "Gas1Id"), "gas2": val(b, "Gas2Id")}
    for s in root.find("Property[@name='RegionHotspotSubstances']").findall("Property"):
        substances.append({"id": val(s, "SubstanceId"), "amount_cost": num(val(s, "AmountCost")), "yield": num(val(s, "SubstanceYeild"))})
    return classes, biome_gases, substances


def parse_buildings(work):
    """Every base part that produces, consumes or stores something on a link grid."""
    parts = {}
    for e in load(work, r"basebuildingobjectstable\.mxml$").iter("Property"):
        if e.get("value") != "GcBaseBuildingEntry":
            continue
        lg = props(e).get("LinkGridData")
        if lg is None:
            continue
        lp = props(lg)
        rate, storage = num(val(lg, "Rate")), num(val(lg, "Storage"))
        hot, envd = val(lg, "DependsOnHotspots"), val(lg, "DependsOnEnvironment")
        if not (rate or storage or hot != "None" or envd != "None"):
            continue
        net = val(props(lp["Connection"])["Network"], "LinkNetworkType")
        deps = []
        for d in lp["DependentConnections"].findall("Property"):
            dp = props(d)
            deps.append({"network": val(props(dp["Connection"])["Network"], "LinkNetworkType"),
                         "rate": num(val(d, "DependentRate")), "effect": val(d, "DependentEffect")})
        parts[val(e, "ID")] = {"network": net, "rate_per_s": rate, "storage": storage,
                               "depends_on_hotspot": None if hot == "None" else hot,
                               "depends_on_environment": None if envd == "None" else envd,
                               "dependencies": deps}
    return parts


def game_build():
    try:
        acf = open(os.path.join(STEAM, "appmanifest_275850.acf")).read()
        return re.search(r'"buildid"\s+"(\d+)"', acf).group(1)
    except Exception:
        return None


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--pcbanks", default=DEFAULT_PCBANKS)
    ap.add_argument("--work", default="/tmp/nmsdata")
    ap.add_argument("--out", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "nms_tables.json"))
    ap.add_argument("--hgpaktool", default="/tmp/hgpaktool")
    ap.add_argument("--mbincompiler", default="/tmp/MBINCompiler-linux")
    args = ap.parse_args()

    extract(args)
    loc = parse_loc(args.work)
    items = parse_items(args.work, loc)
    made, falloff = parse_globals(args.work)
    recipes = parse_recipes(args.work, loc, items, made)
    classes, biome_gases, substances = parse_hotspots(args.work)
    parts = parse_buildings(args.work)
    fleet = parse_fleet(args.work)

    units_per_item = substances[0]["amount_cost"] // substances[0]["yield"]  # 360000 / 250 = 1440
    ext = parts["U_EXTRACTOR_S"]
    libmbin = None
    with open(find(args.work, r"gcrecipetable\.mxml$")[0]) as fh:
        m = re.search(r"MBINCompiler version \(([\d.]+)\)", fh.read(400))
        libmbin = m.group(1) if m else None

    out = {
        "meta": {
            "generated": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
            "game_build_id": game_build(),
            "mbincompiler_version": libmbin,
            "save_key_mapping_url": MAPPING_URL,
            "source": "NMSARC.MetadataEtc/globals/misc/Precache .pak via hgpaktool + MBINCompiler",
        },
        "units": {
            "recipes.time_to_make": "raw TimeToMake from the game table, seconds",
            "recipes.seconds_per_op": "TimeToMake / RefinerSubsMadeInTime (250) for substance results, / RefinerProductsMadeInTime (2) for product results; one op consumes 'ingredients' and yields 'result.amount'. Verify against two save snapshots of one refiner before trusting an ETA.",
            "extraction.resource_units_per_item": "link-grid resource units per inventory item (AmountCost / yield)",
            "extraction.items_per_hour_at_strength_1": "extractor rate_per_s * 3600 / resource_units_per_item, at a class-C hotspot with the extractor on the hotspot centre; multiply by class_strength and the survey-device percentage",
            "buildings.rate_per_s": "link-grid units per second; negative = consumes. Power network units are kP.",
            "buildings.storage": "link-grid units; for Resources networks divide by resource_units_per_item to get items (extractor 250, supply depot 1000); for Power it is kPs (battery 45000); for PlantGrowth it is seconds to mature",
            "fleet.events_by_duration": "number of expedition events per duration class; an expedition lasts events * event_seconds from StartTime",
            "items.<id>.craft": "crafting blueprint: ingredients per craft and units made per craft (CraftAmountMultiplier)",
            "save.base_object.UserData": "for U_EXTRACTOR_S / U_SILO_S the upper 32 bits hold the current fill in resource units (divide by resource_units_per_item); the base's LastUpdateTimestamp says when",
        },
        "refiner": {"made_in_time": made},
        "extraction": {
            "resource_units_per_item": units_per_item,
            "extractor_rate_per_s": ext["rate_per_s"],
            "extractor_storage_items": ext["storage"] // units_per_item,
            "supply_depot_storage_items": parts["U_SILO_S"]["storage"] // units_per_item,
            "items_per_hour_at_strength_1": ext["rate_per_s"] * 3600 / units_per_item,
            "items_per_hour_by_class": {c: ext["rate_per_s"] * 3600 / units_per_item * s
                                        for c, s in classes["Mineral1"]["class_strength"].items()},
            "power_required_kp": -ext["dependencies"][0]["rate"],
            "hotspots": classes,
            "hotspot_falloff": falloff,
            "biome_gases": biome_gases,
            "hotspot_substances": substances,
        },
        "fleet": fleet,
        "buildings": parts,
        "items": items,
        "recipes": recipes,
    }
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w") as fh:
        json.dump(out, fh, indent=1, sort_keys=False)
    print(f"wrote {args.out}: {len(recipes)} recipes ({sum(not r['cooking'] for r in recipes)} refiner, "
          f"{sum(r['cooking'] for r in recipes)} cooking), {len(items)} items, {len(parts)} rated parts")


if __name__ == "__main__":
    main()
