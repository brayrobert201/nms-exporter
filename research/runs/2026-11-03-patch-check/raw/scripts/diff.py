import json
old = json.load(open("/home/bob/Projects/nms-exporter/data/nms_tables.json"))
new = json.load(open("/tmp/nms_tables_new.json"))
def name(i): return (old["items"].get(i) or {}).get("name") or (new.get("items_SUSPECT",{}).get(i) or {}).get("name") or i
def fmt(r): return "%s -> %dx %s (%s s)" % (" + ".join("%dx %s" % (g["amount"], name(g["id"])) for g in r["ingredients"]), r["result"]["amount"], name(r["result"]["id"]), r["time_to_make"])
print("== meta: old", old["meta"]["game_build_id"], "new", new["meta"]["game_build_id"])
o = {r["id"]: r for r in old["recipes"]}; n = {r["id"]: r for r in new["recipes"]}
print("== recipes old %d new %d; old ids dup? %d" % (len(o), len(n), len(old["recipes"]) - len(o)))
for k in sorted(set(n) - set(o)): print(" + ", k, n[k]["name"], "|", n[k]["operation"], "|", fmt(n[k]), "cooking" if n[k]["cooking"] else "refiner")
for k in sorted(set(o) - set(n)): print(" - ", k, o[k]["name"], "|", fmt(o[k]))
for k in sorted(set(o) & set(n)):
    a, b = o[k], n[k]
    diffs = [f for f in ("name", "operation", "cooking", "time_to_make", "result", "ingredients") if a.get(f) != b.get(f)]
    if diffs: print(" ~ ", k, diffs, "\n     old:", fmt(a), a["name"], "\n     new:", fmt(b), b["name"])
def deep(path, a, b, out):
    if isinstance(a, dict) and isinstance(b, dict):
        for k in sorted(set(a) | set(b), key=str):
            if k not in a: out.append(("+", path + "." + str(k), b[k]))
            elif k not in b: out.append(("-", path + "." + str(k), a[k]))
            else: deep(path + "." + str(k), a[k], b[k], out)
    elif a != b: out.append(("~", path, (a, b)))
for sec, oldv in [("fleet", old["fleet"]), ("hotspots", old["extraction"]["hotspots"]), ("biomes_by_star", old["planets"]["biomes_by_star"]), ("labels", old["planets"]["labels"]), ("globals_SUSPECT", None)]:
    out = []
    if sec == "globals_SUSPECT":
        made, fall = new[sec]
        deep("refiner.made_in_time", old["refiner"]["made_in_time"], made, out)
        fo = {k: old["extraction"]["hotspot_falloff"].get(k) for k in fall}
        fo["survey_max_distance_m"] = old["extraction"]["survey_max_distance_m"]
        deep("extraction.falloff", fo, fall, out)
    else:
        deep(sec, oldv, new[sec], out)
    print("== %s: %d differences" % (sec, len(out)))
    for d in out[:60]: print("  ", d[0], d[1], json.dumps(d[2], default=str)[:300])
oi, ni = old["items"], new["items_SUSPECT"]
print("== items_SUSPECT old %d new %d" % (len(oi), len(ni)))
add = sorted(set(ni) - set(oi)); rem = sorted(set(oi) - set(ni))
print(" added %d:" % len(add)); [print("   +", k, ni[k].get("kind"), ni[k].get("name"), ni[k].get("value"), ni[k].get("category")) for k in add[:150]]
print(" removed %d:" % len(rem)); [print("   -", k, oi[k].get("name")) for k in rem[:80]]
ch = {}
for k in sorted(set(oi) & set(ni)):
    for f in sorted(set(oi[k]) | set(ni[k])):
        if oi[k].get(f) != ni[k].get(f): ch.setdefault(f, []).append((k, oi[k].get("name"), oi[k].get(f), ni[k].get(f)))
for f, l in ch.items():
    print(" field %s changed on %d items" % (f, len(l)))
    for x in l[:40]: print("    ", x[0], x[1], json.dumps(x[2], default=str)[:150], "->", json.dumps(x[3], default=str)[:150])
