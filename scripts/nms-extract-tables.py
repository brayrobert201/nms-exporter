#!/usr/bin/env python3
"""Build data/nms_tables.json from the installed No Man's Sky game files.

Pulls the refiner/cooking recipe table, item names, extractor and hotspot
constants, the power/plant rates, and the mission tables (titles, stage
objectives, rewards) straight out of the game's .pak archives, so the numbers
always match the installed build rather than a wiki.

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
           "*NMS_BASEPARTPRODUCTS*", "*NMS_MODULARCUSTOMISATIONPRODUCTS*", "*PROCEDURALPRODUCTTABLE*",
           "*MISSIONS/TABLES*", "*REALITY/TABLES/REWARDTABLE*", "*PROCEDURALTECHNOLOGYTABLE*",
           "*FRIGATETRAITTABLE*"]
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
                # The game's own grouping: substances have a Category (Fuel, Earth, Metal,
                # Stellar, Catalyst, Flora, Exotic, Special), products a Type (Component,
                # Consumable, Tradeable, Curiosity, ...). The storage plan sorts by these.
                cat = props(e).get("Category" if kind == "Substance" else "Type")
                if kind != "Technology" and cat is not None:
                    rec["category"] = cat[0].get("value") if len(cat) else cat.get("value")
                req = props(e).get("Requirements")
                if kind == "Product" and req is not None and val(e, "IsCraftable") == "true":
                    ings = [{"id": val(r, "ID"), "type": val(props(r)["Type"], "InventoryType"), "amount": int(val(r, "Amount"))}
                            for r in req.findall("Property")]
                    if ings:
                        rec["craft"] = {"ingredients": ings, "yield": int(val(e, "CraftAmountMultiplier") or 1)}
                sym = val(e, "Symbol")
                if sym and loc.get(sym):
                    rec["symbol"] = loc[sym]
                if kind == "Technology":
                    # Adjacency bonuses group technologies by the stat they drive.
                    bs = props(e).get("BaseStat")
                    rec["stat"] = (bs[0].get("value") if len(bs) else bs.get("value")) if bs is not None else None
                    cat = props(e).get("Category")
                    rec["category"] = (cat[0].get("value") if len(cat) else cat.get("value")) if cat is not None else None
                    rec["core"] = val(e, "Core") == "true"
                    rec["upgrade"] = val(e, "Upgrade") == "true"
                items[iid] = rec
    # Procedural upgrade modules (UP_JET4, CV_LAUN2, ...). Their Template is a
    # technology entry above, which carries the stat family.
    quality = {"Normal": "C", "Rare": "B", "Epic": "A", "Legendary": "S", "Illegal": "X", "Sentinel": "S", "SeaTrash": "C"}
    for e in load(work, r"gcproceduraltechnologytable\.mxml$").iter("Property"):
        if e.get("value") != "GcProceduralTechnologyData" or not val(e, "ID"):
            continue
        tmpl = val(e, "Template")
        q = props(e).get("Quality")
        q = (q[0].get("value") if len(q) else q.get("value")) if q is not None else None
        base = loc.get(val(e, "NameLower")) or loc.get(val(e, "Name")) or items.get(tmpl, {}).get("name") or tmpl
        items[val(e, "ID")] = {"name": base if base == "Upgrade Module" else f"{base} module", "type": "Technology", "procedural": True,
                               "template": tmpl, "class": quality.get(q, q), "quality": q,
                               "sentinel": q == "Sentinel", "stat": items.get(tmpl, {}).get("stat"),
                               "category": items.get(tmpl, {}).get("category"), "core": False, "upgrade": True}
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


def parse_fleet(work, loc):
    g = load(work, r"gcfleetglobals\.global\.mxml$")
    durations = {d.get("name"): num(d.get("value"))
                 for d in props(props(g)["ExpeditionDurations"])["Duration"].findall("Property")}
    # Trait points per stat type and strength, for scoring a frigate's base roll.
    strengths = {}
    by_type = props(g).get("FrigateTraitStrengths")
    types = props(by_type).get("FrigateStatType") if by_type is not None else None
    for st in (types.findall("Property") if types is not None else []):
        alt = props(st).get("StatAlteration")
        if alt is None:
            continue
        strengths[st.get("name")] = {p.get("name"): num(p.get("value")) for p in alt.findall("Property")}
    traits = {}
    for e in load(work, r"frigatetraittable\.mxml$").iter("Property"):
        if e.get("value") != "GcFrigateTraitData":
            continue
        pp = props(e)
        stat = val(pp["FrigateStatType"], "FrigateStatType")
        strength = val(pp["Strength"], "FrigateTraitStrength")
        traits[val(e, "ID")] = {"name": loc.get(val(e, "DisplayName"), val(e, "DisplayName")), "stat": stat,
                                "strength": strength, "points": strengths.get(stat, {}).get(strength, 0)}
    return {
        "event_seconds": num(val(g, "TimeTakenForExpeditionEvent")),
        "event_seconds_easy": num(val(g, "TimeTakenForExpeditionEvent_Easy")),
        "events_by_duration": durations,
        "passive_income_tick_seconds": num(val(g, "TimeBetweenPassiveIncomeTicks")),
        "stat_points_per_level": num(val(g, "StatPointsAwardedForLevelUp")),
        # Expeditions needed for each rank-up. Not in the globals; the community's
        # frigate calculators (NMSCD/frigate-calculator) use these.
        "level_thresholds_community": [4, 8, 15, 25, 30, 35, 40, 45, 50, 55],
        "trait_points": strengths,
        "traits": traits,
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


# --- missions ------------------------------------------------------------------
# A mission ID can be defined in more than one table; the first table in this
# order wins (stat-story and wiki variants come last).
MISSION_TABLE_ORDER = [
    "coremissiontable", "missiontable", "atlaspathtable", "npcmissiontable", "sentinelsettlementmissiontable",
    "watermissiontable", "tutorialmissiontable", "recurringmissiontable", "communitymissiontable",
    "npcbuildersmissiontable", "spacepoimissiontable", "basecomputermissiontable", "piratemissiontable",
    "fleetmissiontable", "corvettemissiontable", "swarmmissiontable", "planetprocmissiontable",
    "spaceoutpostmissiontable", "startedonusemissiontable", "wikimissiontable", "statstoriesmissiontable"]
# Reward kinds that are bookkeeping, not something the player receives.
REWARD_SKIP = {
    "MissionMessage", "ScanEvent", "ModifyStat", "IncrementStat", "InterventionResponse", "SetInteractionMissionState",
    "OpenPage", "WikiTopic", "RefreshHazProt", "Health", "Shield", "OpenUnlockTree", "RecycleSpecificObject",
    "CommunityContribution", "SettlementParty", "SettlementStat", "WantedLevel", "SettlementCustomJudgement",
    "AtlasPathProgress", "MissionSeeded", "Trigger", "SetMissionStat", "ActivateFiends", "DamageTech",
    "AdvancePortalState", "SendChatMessage", "TriggerMaintenance", "FrigateFlyby", "Worker", "Mission",
    "ExchangeProduct", "UnlockSeasonReward", "TeachSpecificWords"}


PLACEHOLDERS = {"SETTLEMENT": "your settlement"}     # the rest read fine when simply dropped


def clean_text(text):
    """First line of a localised string without markup; %PLACEHOLDERS% the game
    fills at runtime become plain words, or go."""
    text = re.sub(r"<[A-Z_]+>|<>", "", text or "").split("\n")[0]
    text = re.sub(r"%([A-Z_0-9]+)%", lambda m: PLACEHOLDERS.get(m[1], ""), text)
    return re.sub(r"\s+", " ", text).strip().rstrip(":").strip()


def reward_descs(entry, loc, items):
    """Short descriptions of what one reward table entry hands out."""
    def name(i):
        return items.get(i, {}).get("name") or loc.get(i + "_NAME_L") or loc.get(i + "_NAME") or i

    descs = []
    for it in entry.iter("Property"):
        if it.get("value") != "GcRewardTableItem":
            continue
        r = props(it).get("Reward")
        if r is None or not len(r):
            continue
        kind = (r[0].get("name") or "").replace("GcReward", "")
        if kind in REWARD_SKIP:
            continue
        ids, f = [], {}
        for c in r[0].iter("Property"):
            n, v = c.get("name"), c.get("value")
            if not v:
                continue
            if n in ("ID", "TechId", "ProductIds", "TechIds"):
                ids.append(v)
            elif n not in f:
                f[n] = v
        names = ", ".join(dict.fromkeys(name(i) for i in ids[:12]))   # unique, in order
        lo, hi = f.get("AmountMin"), f.get("AmountMax")
        amt = lo if lo == hi else f"{lo}-{hi}" if lo and hi else (lo or f.get("Amount") or "")
        if kind in ("SpecificProduct", "SpecificSubstance", "Product"):
            d = f"{amt} x {names}" if amt and amt != "1" else names
        elif kind in ("MultiSpecificItems", "MultiSpecificProducts"):
            d = names
        elif kind == "SpecificTech":
            d = f"{names} (tech)"
        elif kind in ("SpecificProductRecipe", "MultiSpecificProductRecipes", "SpecificProductRecipeFromList"):
            d = f"blueprint: {names}"
        elif kind == "MultiSpecificTechRecipes":
            d = f"tech blueprint: {names}"
        elif kind == "Money":
            d = f"{amt} units"
        elif kind == "SpecificSpecial":
            d = names
        elif kind == "ProcTechProduct":
            d = f"{clean_text(loc.get(f.get('Group', ''), '')) or 'upgrade'} module"
        elif kind == "TeachWord":
            d = f"{amt or 1} words"
        elif kind == "DiscoverRune":
            d = "portal glyph"
        elif kind == "SpecificShip":
            d = "a starship"
        elif kind == "SpecificFrigate":
            d = "a frigate"
        elif kind == "SpecificWeapon":
            d = "a multi-tool"
        elif kind == "SpecificPetEgg":
            d = "companion egg"
        elif kind == "UnlockTitle":
            d = "a title"
        elif kind in ("Standing", "FactionStanding"):
            d = "standing"
        else:
            d = kind
        if d and d not in descs:
            descs.append(d)
    return descs


def parse_missions(work, loc, items):
    """Titled missions: terminal progress value, stage objectives by progress number, rewards."""
    seqs = {}
    for tbl in MISSION_TABLE_ORDER:
        path = find(work, rf"^{tbl}\.mxml$")
        if not path:
            continue
        for e in ET.parse(path[0]).getroot().iter("Property"):
            if e.get("value") != "GcGenericMissionSequence":
                continue
            mid = val(e, "MissionID")
            if mid and mid not in seqs:
                seqs[mid] = e

    def version_progress(versions):
        vp = {int(val(x, "Version")): int(val(x, "Progress")) for x in versions}
        return vp[max(vp)] if vp else None

    out = {}
    for mid, e in seqs.items():
        pp = props(e)
        tkey = val(pp["MissionTitles"], "Format") if pp.get("MissionTitles") is not None else None
        title = clean_text(loc.get(tkey, "")) if tkey else ""
        if not title:
            continue
        fsv = pp.get("FinalStageVersions")
        final = version_progress(fsv) if fsv is not None and len(fsv) else None
        stages = []

        def walk(stage_list, objective):
            for s in stage_list:
                sp = props(s)
                st = sp.get("Stage")
                inner = st[0] if st is not None and len(st) else None
                if inner is None:
                    continue
                obj = val(inner, "ObjectiveID")
                objective2 = (clean_text(loc.get(obj, "")) if obj else "") or objective
                sub = props(inner).get("Stages")
                if sub is not None and len(sub):
                    walk(sub, objective2)
                    continue
                vers = sp.get("Versions")
                if vers is None or not len(vers):
                    continue
                msg = val(inner, "Message")
                text = objective2 or (clean_text(loc.get(msg, "")) if msg else "")
                if text:
                    stages.append((version_progress(vers), text))

        walk(pp["Stages"], "")
        compact = []
        for num, text in sorted(stages):
            if not compact or compact[-1][1] != text:
                compact.append([num, text])
        rewards, leads = [], []
        for r in (pp.get("Rewards") if pp.get("Rewards") is not None else []):
            for c in r.iter("Property"):
                if c.get("name") == "Mission" and c.get("value"):
                    leads.append(c.get("value"))
            descs = reward_descs(r, loc, items)
            if descs:
                rewards.append([val(r, "Id"), descs])
        out[mid] = {"title": title, "class": val(e, "MissionClass"), "final": final, "stages": compact,
                    "rewards": rewards, "leads_to": sorted(set(leads)), "recurring": val(e, "IsRecurring") == "true"}
    return out


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
    fleet = parse_fleet(args.work, loc)
    missions = parse_missions(args.work, loc, items)

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
            "fleet.traits": "frigate trait id -> display name, the stat it raises and the points it adds (from FrigateTraitStrengths); subtract trait points and level-ups to recover a frigate's base roll",
            "fleet.events_by_duration": "number of expedition events per duration class; an expedition lasts events * event_seconds from StartTime",
            "items.<id>.craft": "crafting blueprint: ingredients per craft and units made per craft (CraftAmountMultiplier)",
            "items.<id>.category": "substance Category or product Type from the game tables, the grouping data/nms_storage_plan.json sorts by",
            "items.<id>.stat": "technology only: the stat family (BaseStat) adjacency bonuses group by; procedural modules take it from their template",
            "missions.<id>": "final = the save's MissionProgress.Progress value once the mission is complete (-1 = never started); stages = [progress number, objective] for the latest mission version, so the current objective is the last stage whose number <= Progress; rewards = [reward id, descriptions]; leads_to = missions this one starts",
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
        "missions": missions,
    }
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w") as fh:
        json.dump(out, fh, indent=1, sort_keys=False)
    print(f"wrote {args.out}: {len(recipes)} recipes ({sum(not r['cooking'] for r in recipes)} refiner, "
          f"{sum(r['cooking'] for r in recipes)} cooking), {len(items)} items, {len(parts)} rated parts, "
          f"{len(missions)} missions")


if __name__ == "__main__":
    main()
