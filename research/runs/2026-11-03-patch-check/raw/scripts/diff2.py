import json
old = json.load(open("/home/bob/Projects/nms-exporter/data/nms_tables.json"))
new = json.load(open("/tmp/nms_tables_new.json"))
oi, ni = old["items"], new["items_SUSPECT"]
st = [(k, oi[k].get("name"), oi[k].get("stack"), ni[k].get("stack")) for k in oi if k in ni and oi[k].get("stack") != ni[k].get("stack") and oi[k].get("stack") is not None]
print("stack changed where old had a value:", len(st)); [print("  ", x) for x in st[:30]]
from collections import Counter
print("old stack values", Counter(v.get("stack") for v in oi.values() if "stack" in v).most_common(10))
print("new stack values", Counter(v.get("stack") for v in ni.values() if "stack" in v).most_common(10))
print("null->0 kinds", Counter((oi[k].get("category")) for k in oi if k in ni and oi[k].get("stack") is None and ni[k].get("stack") == 0).most_common(8))
cl, gases, subs = new["hotspots"]
o = old["extraction"]
print("classes same:", cl == o["hotspots"], "| biome_gases same:", gases == o["biome_gases"], "| substances same:", subs == o["hotspot_substances"])
if gases != o["biome_gases"]:
    for k in set(gases) | set(o["biome_gases"]):
        if gases.get(k) != o["biome_gases"].get(k): print("  gas", k, o["biome_gases"].get(k), "->", gases.get(k))
if subs != o["hotspot_substances"]: print(" subs old", o["hotspot_substances"], "\n new", subs)
# fields per item: which fields exist in new but not old
print("fields old", Counter(f for v in oi.values() for f in v).most_common()); print("fields new", Counter(f for v in ni.values() for f in v).most_common())
add = sorted(set(ni) - set(oi))
print("added by category", Counter(ni[k].get("category") for k in add).most_common())
for k in add:
    if ni[k].get("category") != "BuildingPart" or not k.startswith("B_STR"): print("  +", k, ni[k].get("name"), ni[k].get("category"), ni[k].get("value"), ni[k].get("craft"))
