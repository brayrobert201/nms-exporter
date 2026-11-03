import json, re, glob, collections
raw = json.load(open("/tmp/patchcheck/save4-raw.json"))
old = {m["Key"]: m["Value"] for m in json.load(open("/home/bob/Projects/nms-exporter/data/nms_mapping.json"))["Mapping"]}
new = {m["Key"]: m["Value"] for m in json.load(open("/tmp/mbinc-7.10.0-pre1/mapping.json"))["Mapping"]}
seen = collections.Counter(); paths = {}
def walk(o, path):
    if isinstance(o, dict):
        for k, v in o.items():
            seen[k] += 1; paths.setdefault(k, path)
            walk(v, path + "/" + old.get(k, new.get(k, k)))
    elif isinstance(o, list):
        for v in o[:50]: walk(v, path + "[]")
walk(raw, "")
unmapped = [k for k in seen if k not in old]
print("distinct keys in save:", len(seen), "unmapped by data/nms_mapping.json:", len(unmapped))
for k in sorted(unmapped, key=lambda k: paths[k]): print("  %r -> %s (x%d) at %s" % (k, new.get(k, "?? not in 7.10 mapping either"), seen[k], paths[k]))
# keys the exporter code reads
names = set()
for f in glob.glob("/home/bob/Projects/nms-exporter/nmsexporter/*.py") + ["/home/bob/Projects/nms-exporter/nms_exporter.py"]:
    s = open(f).read()
    names |= set(re.findall(r"""(?:\.get\(|\[)\s*["']([A-Z][A-Za-z0-9]+)["']""", s))
mapped_names = set(old.values()) | set(new.values())
save_names = {old.get(k, new.get(k, k)) for k in seen}
cand = sorted(n for n in names if n in mapped_names)
missing = [n for n in cand if n not in save_names]
print("save-key names the code reads (that are mapping values):", len(cand))
print("of those, absent from this save:", missing)
