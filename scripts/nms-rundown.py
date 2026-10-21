#!/usr/bin/env python3
"""One-screen rundown of the exporter's /json: the answer to "check my state".

    scripts/nms-rundown.py            # the full rundown, plain text
    scripts/nms-rundown.py --short    # one line, for a status bar
    scripts/nms-rundown.py --diff     # what changed since the previous save

Standard library only. Exits 0 with an explanation when the exporter is down.
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.request

URL = os.environ.get("NMS_EXPORTER_URL", "http://127.0.0.1:9877")


def fetch(path: str):
    with urllib.request.urlopen(URL + path, timeout=5) as r:
        return json.load(r)


def fdur(sec) -> str:
    if sec is None:
        return "--"
    s = max(0, int(sec))
    d, h, m = s // 86400, (s % 86400) // 3600, (s % 3600) // 60
    return f"{d}d {h}h" if d else f"{h}h {m:02d}m" if h else f"{m}m"


def fbig(v) -> str:
    v = v or 0
    for div, unit in ((1e9, "B"), (1e6, "M"), (1e3, "k")):
        if abs(v) >= div * 10:
            return f"{v / div:,.1f}{unit}"
    return f"{v:,.0f}"


def run_counts(run: dict) -> str:
    names = run.get("names") or {}
    parts = [f"{n} {names.get(t, t)}" for t, n in (run.get("counts") or {}).items() if n]
    return ", ".join(parts) if parts else "nothing"


def plan_line(d) -> str:
    p = d.get("planner") or {}
    return run_counts(p.get("best_now") or {})


def short(d) -> str:
    age = d.get("save", {}).get("age") or 0
    farms = [f for f in (d.get("farms") or {}).values() if f.get("full_in_seconds") is not None]
    nxt = min(farms, key=lambda f: f["full_in_seconds"]) if farms else None
    plants = d.get("plants") or {}
    ready = sum(1 for b in plants.values() for q in b["plants"] if (q.get("ready_in_seconds") or 0) <= 0)
    total = sum(len(b["plants"]) for b in plants.values())
    p = d.get("planner") or {}
    best = (p.get("best_now") or {}).get("value") or 0
    return (f"NMS save {fdur(age)} ago · {fbig(d['player']['units'])} units · craft {plan_line(d)} ({fbig(best)})"
            f" · next farm {nxt['name'] if nxt else '--'} full in {fdur(nxt['full_in_seconds']) if nxt else '--'}"
            f" · plants {ready}/{total} ready")


def full(d) -> str:
    out = []
    s = d.get("save", {})
    out.append(f"Save {s.get('file')} · {s.get('summary')} · {fdur(s.get('age'))} ago"
               f" · {fbig(d['player']['units'])} units · {d['player']['nanites']:,} nanites")
    if d.get("errors"):
        out.append("Errors: " + ", ".join(f"{k}: {v}" for k, v in d["errors"].items()))
    p = d.get("planner") or {}
    if p:
        out.append("")
        out.append("Craftable now: " + plan_line(d) + f" = {fbig((p.get('best_now') or {}).get('value'))}")
        for t in p.get("targets", []):
            b = t.get("blocker")
            blk = f"blocked by {b['item']} ({b['have']} of {b['need']})" if b else "no blocker"
            out.append(f"  {t['item']:16s} now {t['now']:3d}, after harvest {t['after_harvest']:3d}  ·  {blk}")
        after = p.get("best_after_harvest") or {}
        out.append(f"  after a full harvest: {run_counts(after)} = {fbig(after.get('value'))}")
    out.append("")
    out.append("Farms, soonest full first:")
    farms = sorted((d.get("farms") or {}).values(), key=lambda f: f.get("full_in_seconds") or 1e12)
    for f in farms:
        label = f['name'] if f.get('base') in (None, f['name']) else f"{f['name']} ({f['base']})"
        out.append(f"  {label:34s} {f['fill_ratio'] * 100:3.0f}%  {f['rate_items_per_hour']:5.0f}/h"
                   f" {'measured' if f.get('rate_measured') else 'assumed'}  full in {fdur(f.get('full_in_seconds'))}")
    out.append("")
    out.append("Refiners:")
    for r in d.get("refiners") or []:
        state = "running" if r.get("active") else ("stalled at cap" if r.get("stalls_at_cap") and r.get("ops_remaining") else "idle")
        out.append(f"  {r['base']:18s} {r['recipe']:26s} -> {r['output']} {r['projected_output']:.0f}/{r['output_cap'] or '-'}  {state}")
    out.append("")
    out.append("Plants:")
    agg: dict = {}
    for b in (d.get("plants") or {}).values():
        for q in b["plants"]:
            a = agg.setdefault(q["yields"], [0, 0, 1e12, 0.0])
            a[0] += 1
            a[1] += 1 if (q.get("ready_in_seconds") or 0) <= 0 else 0
            a[2] = min(a[2], q.get("ready_in_seconds") or 0)
            a[3] = max(a[3], q.get("ready_in_seconds") or 0)
    for k, (n, ready, nxt, last) in sorted(agg.items(), key=lambda kv: -kv[1][0]):
        out.append(f"  {k:16s} {n:4d} planted, {ready:4d} ready, next in {fdur(nxt)}, all by {fdur(last)}")
    return "\n".join(out)


def diff_text(dd) -> str:
    if not dd or dd.get("error"):
        return f"diff: {dd.get('error') if dd else 'unavailable'}"
    out = [f"Since {time.strftime('%a %H:%M', time.localtime(dd['from']['timestamp']))}"
           f" ({dd['from']['file']}) to {time.strftime('%a %H:%M', time.localtime(dd['to']['timestamp']))}:"]
    out.append(f"  units {dd['units']['from']:,} -> {dd['units']['to']:,} ({dd['units']['delta']:+,})")
    for it in dd.get("items", [])[:25]:
        out.append(f"  {it['item']:28s} {it['from']:8d} -> {it['to']:8d} ({it['delta']:+d})")
    return "\n".join(out)


def main():
    try:
        if "--diff" in sys.argv:
            print(diff_text(fetch("/diff")))
            return
        d = fetch("/json")
    except Exception as e:
        print(f"nms-exporter not reachable at {URL}: {e}")
        return
    print(short(d) if "--short" in sys.argv else full(d))


if __name__ == "__main__":
    main()
