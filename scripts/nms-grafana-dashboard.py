#!/usr/bin/env python3
"""Generate the Grafana dashboard for the No Man's Sky exporter.

Usage: scripts/nms-grafana-dashboard.py [OUT.json]
Default output is ../grafana/no-mans-sky.json; copy it wherever your Grafana
provisions dashboards from (a ConfigMap for the sidecar, or import it by hand).

Design follows the data-viz skill's validated dark palette, same as the wall
displays: categorical slots in fixed order for series, status hues reserved for
state, one axis per chart, direct labels where they fit.
"""
import json
import os
import sys

DS = {"type": "prometheus", "uid": "prometheus"}
SERIES = ["#3987e5", "#d95926", "#199e70", "#c98500", "#d55181", "#008300", "#9085e9", "#e66767"]
BLUE, INK2 = SERIES[0], "#c3c2b7"
GOOD, WARN, SERIOUS, CRIT = "#0ca30c", "#fab219", "#ec835a", "#d03b3b"

_id = [0]


def nid():
    _id[0] += 1
    return _id[0]


def target(expr, legend="", instant=False, ref="A", fmt=None):
    t = {"datasource": DS, "refId": ref, "expr": expr, "legendFormat": legend}
    if instant:
        t["instant"] = True
        t["range"] = False
    if fmt:
        t["format"] = fmt
    return t


def panel(ptype, title, x, y, w, h, targets, unit=None, color=BLUE, decimals=None, extra=None, defaults=None,
          overrides=None, options=None, transformations=None, description=None):
    d = {"color": {"mode": "fixed", "fixedColor": color}, "thresholds": {"mode": "absolute", "steps": [{"color": color, "value": None}]}}
    if unit:
        d["unit"] = unit
    if decimals is not None:
        d["decimals"] = decimals
    if defaults:
        d.update(defaults)
    p = {"id": nid(), "type": ptype, "title": title, "datasource": DS,
         "gridPos": {"x": x, "y": y, "w": w, "h": h}, "targets": targets,
         "fieldConfig": {"defaults": d, "overrides": overrides or []}, "options": options or {}}
    if description:
        p["description"] = description
    if transformations:
        p["transformations"] = transformations
    if extra:
        p.update(extra)
    return p


def stat(title, expr, x, y, w=3, h=4, unit="short", color=INK2, decimals=None, legend="", text_mode="value",
         thresholds=None, description=None, instant=True):
    opts = {"reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False},
            "textMode": text_mode, "colorMode": "value" if thresholds else "none", "graphMode": "none",
            "justifyMode": "auto", "wideLayout": True}
    p = panel("stat", title, x, y, w, h, [target(expr, legend, instant=instant)], unit, color, decimals,
              options=opts, description=description)
    if thresholds:
        p["fieldConfig"]["defaults"]["color"] = {"mode": "thresholds"}
        p["fieldConfig"]["defaults"]["thresholds"] = {"mode": "absolute", "steps": thresholds}
    return p


def stats(title, items, x, y, w, h, color=INK2, background=False, description=None):
    """One stat panel holding several values; wraps to fit, so it stays compact on a phone.
    items: list of dicts with name, expr and optional unit, decimals, mappings, thresholds."""
    targets, overrides = [], []
    for i, it in enumerate(items):
        ref = chr(65 + i)
        targets.append(target(it["expr"], it["name"], instant=True, ref=ref))
        props = []
        if it.get("unit"):
            props.append({"id": "unit", "value": it["unit"]})
        if it.get("decimals") is not None:
            props.append({"id": "decimals", "value": it["decimals"]})
        if it.get("mappings"):
            props.append({"id": "mappings", "value": it["mappings"]})
        if it.get("thresholds"):
            props.append({"id": "thresholds", "value": {"mode": "absolute", "steps": it["thresholds"]}})
            props.append({"id": "color", "value": {"mode": "thresholds"}})
        if props:
            overrides.append({"matcher": {"id": "byFrameRefID", "options": ref}, "properties": props})
    opts = {"reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False},
            "textMode": "value_and_name", "colorMode": "background" if background else "none", "graphMode": "none",
            "justifyMode": "center", "orientation": "auto", "wideLayout": False,
            "text": {"titleSize": 12, "valueSize": 22}}   # fixed sizes so three values fit a 412px phone screen
    return panel("stat", title, x, y, w, h, targets, "short", color, options=opts, overrides=overrides, description=description)


def bargauge(title, expr, legend, x, y, w, h, unit="percentunit", vmin=0, vmax=1, color=BLUE, description=None, targets=None):
    opts = {"reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False},
            "orientation": "horizontal", "displayMode": "basic", "showUnfilled": True, "valueMode": "color",
            "namePlacement": "top", "sizing": "auto", "minVizHeight": 16, "maxVizHeight": 32}
    return panel("bargauge", title, x, y, w, h, targets or [target(expr, legend, instant=True)], unit, color,
                 defaults={"min": vmin, "max": vmax}, options=opts, description=description)


def timeseries(title, targets, x, y, w, h, unit="short", vmin=None, vmax=None, fill=0, description=None, legend_right=False):
    custom = {"lineWidth": 2, "fillOpacity": fill, "pointSize": 5, "showPoints": "never", "spanNulls": True,
              "gradientMode": "none", "drawStyle": "line", "lineInterpolation": "linear", "axisBorderShow": False}
    d = {"custom": custom}
    if vmin is not None:
        d["min"] = vmin
    if vmax is not None:
        d["max"] = vmax
    overrides = []
    # fixed categorical order for multi-series panels: override the palette by index
    if len(targets) == 1:
        d["color"] = {"mode": "palette-classic"}
    opts = {"legend": {"displayMode": "table" if legend_right else "list", "placement": "right" if legend_right else "bottom",
                       "showLegend": True, "calcs": ["lastNotNull"] if legend_right else []},
            "tooltip": {"mode": "multi", "sort": "desc"}}
    p = panel("timeseries", title, x, y, w, h, targets, unit, BLUE, defaults=d, overrides=overrides, options=opts,
              description=description)
    # palette-classic would cycle Grafana's own hues; pin ours in order instead
    p["fieldConfig"]["defaults"]["color"] = {"mode": "palette-classic-by-name"}
    p["fieldConfig"]["overrides"] = [{"matcher": {"id": "byFrameRefID", "options": t["refId"]},
                                      "properties": [{"id": "color", "value": {"mode": "fixed", "fixedColor": SERIES[i % len(SERIES)]}}]}
                                     for i, t in enumerate(targets)] if len(targets) > 1 else []
    if len(targets) == 1:
        p["fieldConfig"]["defaults"]["color"] = {"mode": "fixed", "fixedColor": BLUE}
    return p


def table(title, targets, x, y, w, h, columns, sort=None, description=None, extra_transforms=None, overrides=None):
    """columns: ordered list of (source field, display name, unit or None, extra fieldConfig)."""
    rename = {src: name for src, name, *_ in columns}
    index = {src: i for i, (src, *_) in enumerate(columns)}   # Grafana keys indexByName by the original field name
    # drop __name__ first, otherwise merge sees every query's rows as distinct
    tr = [{"id": "organize", "options": {"excludeByName": {"__name__": True}}}, {"id": "merge", "options": {}}] if len(targets) > 1 else []
    tr += extra_transforms or []
    tr.append({"id": "organize", "options": {"excludeByName": {"Time": True, "__name__": True, "job": True, "instance": True, "host": True, "id": True},
                                              "renameByName": rename, "indexByName": index}})
    if sort:
        tr.append({"id": "sortBy", "options": {"sort": [{"field": sort[0], "desc": sort[1]}]}})
    ov = list(overrides or [])
    for src, name, *rest in columns:
        unit = rest[0] if rest else None
        props = []
        if unit:
            props.append({"id": "unit", "value": unit})
        if len(rest) > 1 and rest[1]:
            props += rest[1]
        if props:
            ov.append({"matcher": {"id": "byName", "options": name}, "properties": props})
    opts = {"showHeader": True, "cellHeight": "sm", "footer": {"show": False}}
    return panel("table", title, x, y, w, h, targets, None, BLUE, defaults={"custom": {"align": "auto", "cellOptions": {"type": "auto"}, "filterable": True}},
                 overrides=ov, options=opts, transformations=tr, description=description)


def row(title, y):
    return {"id": nid(), "type": "row", "title": title, "collapsed": False, "gridPos": {"x": 0, "y": y, "w": 24, "h": 1}, "panels": []}


GAUGE_CELL = [{"id": "custom.cellOptions", "value": {"type": "gauge", "mode": "basic", "valueDisplayMode": "text"}},
              {"id": "min", "value": 0}, {"id": "max", "value": 1}, {"id": "color", "value": {"mode": "fixed", "fixedColor": BLUE}}]
DUR = "dtdurations"
WHEN = "dateTimeAsLocalNoDateIfToday"


NONE = [{"type": "value", "options": {"0": {"text": "none pending"}}}]
OK = [{"color": CRIT, "value": None}, {"color": GOOD, "value": 1}]
OKMAP = [{"type": "value", "options": {"0": {"text": "✕ down"}, "1": {"text": "✓ ok"}}}]


def build():
    """Portrait-first: related numbers share one panel (they wrap on a phone), tables and charts span the width."""
    P = []
    y = 0
    # ---------------------------------------------------------------- right now
    P.append(row("Right now", y)); y += 1
    where = stat("Where", "nms_save_info", 0, y, 16, 3, legend="{{summary}}", text_mode="name",
                 description="The game's own save summary")
    where["options"]["text"] = {"valueSize": 22}
    P.append(where)
    P.append(stat("Save age", "nms_save_age_seconds", 16, y, 8, 3, unit=DUR,
                  description="How long ago the game last wrote a save. Everything marked projected is extrapolated from that point."))
    y += 3
    P.append(stats("Currency", [dict(name="Units", expr="nms_units", decimals=1), dict(name="Nanites", expr="nms_nanites"),
                                dict(name="Quicksilver", expr="nms_quicksilver")], 0, y, 12, 4))
    P.append(stats("Time", [dict(name="Play time", expr="nms_play_time_seconds", unit=DUR), dict(name="This life", expr="nms_time_alive_seconds", unit=DUR),
                            dict(name="Galaxy", expr='nms_universe_address{axis="galaxy"}')], 12, y, 12, 4))
    y += 4
    P.append(bargauge("Vitals", None, None, 0, y, 16, 4, unit="none", vmin=0, vmax=100,
                      targets=[target("nms_health", "Health", instant=True, ref="A"), target("nms_shield", "Shield", instant=True, ref="B"),
                               target("nms_life_support", "Life support", instant=True, ref="C")]))
    P.append(stats("Ship", [dict(name="Ship health", expr="nms_ship_health")], 16, y, 8, 4))
    y += 4
    # ---------------------------------------------------------------- refiners
    P.append(row("Refiners (projected from the save's timestamps)", y)); y += 1
    P.append(stats("Refiners", [dict(name="Running", expr="count(nms_refiner_active == 1) or vector(0)"),
                                dict(name="Ready to collect", expr="count(nms_refiner_active == 0 and nms_refiner_output_amount > 0) or vector(0)"),
                                dict(name="Next finish", expr="min(nms_refiner_remaining_seconds > 0) or vector(0)", unit=DUR, mappings=NONE)],
                   0, y, 24, 4, description="Ready to collect = finished refiners that still hold output"))
    y += 4
    P.append(table("Refiners", [
        target("nms_refiner_output_amount", instant=True, ref="A", fmt="table"),
        target("sum by (refiner, recipe, output) (nms_refiner_input_amount)", instant=True, ref="B", fmt="table"),
        target("nms_refiner_progress_ratio", instant=True, ref="C", fmt="table"),
        target("nms_refiner_remaining_seconds", instant=True, ref="D", fmt="table"),
        target("nms_refiner_finish_timestamp_seconds * 1000", instant=True, ref="E", fmt="table"),
    ], 0, y, 24, 11, [("output", "Makes"), ("Value #A", "Output", "short"), ("Value #C", "Progress", "percentunit", GAUGE_CELL),
                      ("Value #D", "Remaining", DUR), ("Value #E", "Done at", WHEN), ("Value #B", "Input left", "short"),
                      ("recipe", "Recipe"), ("refiner", "Refiner")],
        sort=("Remaining", True), description="Newest state per refiner. Output and input are projected forward using the recipe's rate."))
    y += 11
    ts = timeseries("Running refiners: input left, projected",
                    [target("nms_refiner_input_amount and on(refiner, recipe, output) nms_refiner_active == 1", "{{input}} → {{output}} · {{refiner}}")],
                    0, y, 24, 8, description="Only refiners with work left; empty means nothing is running")
    ts["fieldConfig"]["defaults"]["noValue"] = "Nothing running"
    P.append(ts)
    y += 8
    # ---------------------------------------------------------------- farms
    P.append(row("Extraction farms (projected)", y)); y += 1
    P.append(bargauge("Storage used", "nms_farm_fill_ratio", "{{base}}", 0, y, 16, 6,
                      description="Extractors plus supply depots, projected from the last save at the measured rate"))
    P.append(stats("Farms", [dict(name="Next farm full in", expr="min(nms_farm_full_in_seconds > 0) or vector(0)", unit=DUR, mappings=NONE),
                             dict(name="Total stored", expr="sum(nms_farm_stored_items)", decimals=0)], 16, y, 8, 6))
    y += 6
    P.append(table("Farms", [
        target("nms_farm_stored_items", instant=True, ref="A", fmt="table"),
        target("nms_farm_capacity_items", instant=True, ref="B", fmt="table"),
        target("nms_farm_rate_items_per_hour", instant=True, ref="C", fmt="table"),
        target("nms_farm_rate_measured", instant=True, ref="D", fmt="table"),
        target("nms_farm_full_in_seconds", instant=True, ref="E", fmt="table"),
        target("nms_farm_extractors", instant=True, ref="F", fmt="table"),
        target("nms_farm_depots", instant=True, ref="G", fmt="table"),
    ], 0, y, 24, 6, [("base", "Base"), ("Value #E", "Full in", DUR), ("Value #A", "Stored", "short"), ("Value #B", "Capacity", "short"),
                     ("Value #C", "Rate /h", "short"), ("Value #D", "Rate", None,
                      [{"id": "mappings", "value": [{"type": "value", "options": {"0": {"text": "assumed C-class"}, "1": {"text": "measured"}}}]}]),
                     ("kind", "Kind"), ("Value #F", "Extractors"), ("Value #G", "Depots")],
        sort=("Full in", False), description="Rate is measured from consecutive saves once two differing fill levels exist; until then it assumes a class-C hotspot."))
    y += 6
    P.append(timeseries("Storage used over time", [target("nms_farm_fill_ratio", "{{base}}")], 0, y, 24, 8, unit="percentunit", vmin=0, vmax=1))
    y += 8
    # ---------------------------------------------------------------- fleet
    P.append(row("Fleet", y)); y += 1
    P.append(stats("Fleet", [dict(name="Frigates", expr="sum(nms_frigates)"),
                             dict(name="Expeditions out", expr="count(nms_expedition_returned == 0) or vector(0)"),
                             dict(name="Next return", expr="min(nms_expedition_remaining_seconds > 0) or vector(0)", unit=DUR, mappings=NONE)], 0, y, 24, 4))
    y += 4
    P.append(bargauge("Voyage progress", "nms_expedition_progress_ratio", "{{category}} · {{duration}}", 0, y, 24, 5))
    y += 5
    P.append(table("Expeditions", [
        target("nms_expedition_progress_ratio", instant=True, ref="A", fmt="table"),
        target("nms_expedition_remaining_seconds", instant=True, ref="B", fmt="table"),
        target("nms_expedition_eta_seconds * 1000", instant=True, ref="C", fmt="table"),
        target("nms_expedition_frigates", instant=True, ref="D", fmt="table"),
        target("nms_expedition_events_done", instant=True, ref="E", fmt="table"),
        target("nms_expedition_events", instant=True, ref="F", fmt="table"),
        target("nms_expedition_events_failed", instant=True, ref="G", fmt="table"),
        target("nms_expedition_frigates_damaged", instant=True, ref="H", fmt="table"),
    ], 0, y, 24, 6, [("category", "Category"), ("Value #B", "Back in", DUR), ("Value #C", "Due", WHEN),
                     ("Value #A", "Progress", "percentunit", GAUGE_CELL), ("duration", "Length"), ("Value #D", "Frigates"),
                     ("Value #E", "Events done"), ("Value #F", "Events"), ("Value #G", "Failed"), ("Value #H", "Damaged")],
        sort=("Back in", False), description="Event results only update while the game runs; the timing is projected from departure.",
        extra_transforms=[{"id": "organize", "options": {"excludeByName": {"expedition": True}}}]))
    y += 6
    # ---------------------------------------------------------------- inventory
    P.append(row("Inventory", y)); y += 1
    P.append(stats("Inventory", [dict(name="Distinct items", expr="count(nms_item_total)"), dict(name="Stacks", expr="sum(nms_item_stacks)"),
                                 dict(name="Ammo", expr='nms_ammo{weapon="bolt"}')], 0, y, 24, 4))
    y += 4
    P.append(panel("barchart", "Top 20 by amount", 0, y, 24, 13,
                   [target("topk(20, nms_item_total{type=~\"$type\"})", instant=True, ref="A", fmt="table")],
                   unit="short", color=BLUE,
                   defaults={"custom": {"axisPlacement": "auto", "fillOpacity": 90, "lineWidth": 0, "axisBorderShow": False}},
                   options={"orientation": "horizontal", "xField": "item", "showValue": "always", "barWidth": 0.7, "groupWidth": 0.7,
                            "legend": {"showLegend": False}, "tooltip": {"mode": "single"}, "text": {"valueSize": 12}},
                   transformations=[{"id": "organize", "options": {"excludeByName": {"Time": True, "id": True, "type": True, "__name__": True, "job": True, "instance": True, "host": True}}},
                                    {"id": "sortBy", "options": {"sort": [{"field": "Value", "desc": True}]}}],
                   description="Every container summed: exosuit, ships, freighter, storage, exocraft. Supply depots are on the farms row."))
    y += 13
    P.append(table("Where is it?", [target("nms_item_amount{item=~\"$item\", type=~\"$type\"}", instant=True, ref="A", fmt="table")],
                   0, y, 24, 11, [("item", "Item"), ("location", "Where"), ("Value", "Amount", "short"), ("type", "Type")],
                   sort=("Amount", True), description="Pick items in the Item selector above, or type in the column filter"))
    y += 11
    P.append(table("Totals", [target("nms_item_total{item=~\"$item\", type=~\"$type\"}", instant=True, ref="A", fmt="table"),
                              target("nms_item_stacks{item=~\"$item\", type=~\"$type\"}", instant=True, ref="B", fmt="table")],
                   0, y, 24, 11, [("item", "Item"), ("Value #A", "Total", "short"), ("Value #B", "Stacks"), ("type", "Type")],
                   sort=("Total", True)))
    y += 11
    P.append(timeseries("Totals over time", [target("topk(8, nms_item_total{item=~\"$item\", type=~\"$type\"})", "{{item}}")],
                        0, y, 24, 8, description="Top eight of the selected items"))
    y += 8
    # ---------------------------------------------------------------- plants
    P.append(row("Plants", y)); y += 1
    P.append(stats("Plants", [dict(name="Ready to harvest", expr="sum(nms_plants_mature) or vector(0)"),
                              dict(name="Planted", expr="sum(nms_plants_total) or vector(0)")], 0, y, 24, 4))
    y += 4
    P.append(table("Plants", [target("nms_plant_ready_in_seconds", instant=True, ref="A", fmt="table")], 0, y, 24, 5,
                   [("plant", "Plant"), ("Value", "Ready in", DUR), ("base", "Base"), ("index", "#")], sort=("Ready in", False)))
    y += 5
    # ---------------------------------------------------------------- lifetime
    P.append(row("Lifetime", y)); y += 1
    P.append(stats("Discovery", [dict(name="Planets found", expr='nms_stat{stat="DISC_PLANETS"}'), dict(name="Systems found", expr='nms_stat{stat="DISC_SYSTEMS"}'),
                                 dict(name="Creatures found", expr='nms_stat{stat="DISC_CREATURES"}'), dict(name="Words learnt", expr='nms_stat{stat="WORDS_LEARNT"}'),
                                 dict(name="Discoveries", expr='nms_collection_count{kind="discoveries"}'), dict(name="Warps", expr='nms_stat{stat="DIST_WARP"}')],
                   0, y, 24, 5))
    y += 5
    P.append(stats("Combat", [dict(name="Deaths", expr='nms_stat{stat="DEATHS"}'), dict(name="Sentinels killed", expr='nms_stat{stat="SENTINEL_KILLS"}'),
                              dict(name="Pirates killed", expr='nms_stat{stat="PIRATES_KILLED"}'), dict(name="Sessions", expr='nms_stat{stat="PLAY_SESSIONS"}')],
                   0, y, 12, 5))
    P.append(stats("Distance", [dict(name="Walked", expr='nms_stat{stat="DIST_WALKED"} / 1000', unit="lengthkm", decimals=1),
                                dict(name="Flown", expr='nms_stat{stat="DIST_FLY"} / 1000', unit="lengthkm", decimals=1),
                                dict(name="Jetpacked", expr='nms_stat{stat="DIST_JETPACK"} / 1000', unit="lengthkm", decimals=1),
                                dict(name="In exocraft", expr='nms_stat{stat="DIST_EXO"} / 1000', unit="lengthkm", decimals=1)], 12, y, 12, 5))
    y += 5
    P.append(stats("Earned ever", [dict(name="Units", expr='nms_stat{stat="MONEY_EVER"}', decimals=1),
                                   dict(name="Nanites", expr='nms_stat{stat="NANITES_EVER"}')], 0, y, 24, 4))
    y += 4
    P.append(timeseries("Units", [target("nms_units", "units")], 0, y, 24, 7, unit="short"))
    y += 7
    P.append(timeseries("Nanites", [target("nms_nanites", "nanites")], 0, y, 24, 7, unit="short"))
    y += 7
    P.append(timeseries("Collections", [target("nms_collection_count{kind=~\"ships|multitools|pets|frigates|bases|visited_systems\"}", "{{kind}}")],
                        0, y, 24, 8, legend_right=True))
    y += 8
    # ---------------------------------------------------------------- health
    P.append(row("Exporter", y)); y += 1
    P.append(stats("Status", [dict(name="Collector", expr="nms_collector_up", thresholds=OK, mappings=OKMAP),
                              dict(name="Scrape", expr='up{job="nms"}', thresholds=OK, mappings=OKMAP)], 0, y, 8, 4, background=True,
                   description="Collector = save decoded and metrics current; Scrape = VictoriaMetrics reaching the exporter"))
    P.append(stats("Decoder", [dict(name="Decode time", expr="nms_collector_decode_duration_seconds", unit="s", decimals=2),
                               dict(name="Decodes", expr="nms_collector_decodes_total"),
                               dict(name="Failures", expr="nms_collector_decode_failures_total")], 8, y, 16, 4))
    y += 4
    P.append(timeseries("Save age", [target("nms_save_age_seconds", "age")], 0, y, 24, 6, unit=DUR))
    return {
        "uid": "no-mans-sky", "title": "No Man's Sky", "tags": ["games", "no-mans-sky"], "editable": True,
        "schemaVersion": 39, "graphTooltip": 1, "fiscalYearStartMonth": 0, "timezone": "browser",
        "time": {"from": "now-3h", "to": "now"}, "refresh": "auto",
        "timepicker": {"refresh_intervals": ["auto", "15s", "30s", "1m", "5m", "15m"]},
        "links": [{"title": "Crafting", "type": "link", "url": "/d/no-mans-sky-crafting", "icon": "dashboard", "keepTime": True}], "annotations": {"list": []},
        "description": "Read from the newest save file by nms-exporter. Anything marked projected is extrapolated from the save's own timestamps at the game's rates.",
        "templating": {"list": [
            {"name": "item", "label": "Item", "type": "query", "datasource": DS, "query": {"query": "label_values(nms_item_total, item)", "refId": "v"},
             "definition": "label_values(nms_item_total, item)", "multi": True, "includeAll": True, "allValue": ".*",
             "current": {"text": "All", "value": "$__all"}, "refresh": 2, "sort": 1, "options": []},
            {"name": "type", "label": "Type", "type": "custom", "query": "Substance,Product", "multi": True, "includeAll": True, "allValue": ".*",
             "current": {"text": "All", "value": "$__all"}, "options": [{"text": "All", "value": "$__all", "selected": True},
                                                                       {"text": "Substance", "value": "Substance", "selected": False},
                                                                       {"text": "Product", "value": "Product", "selected": False}]},
        ]},
        "panels": P,
    }


if __name__ == "__main__":
    here = os.path.dirname(os.path.abspath(__file__))
    out = sys.argv[1] if len(sys.argv) > 1 else os.path.join(here, "..", "grafana", "no-mans-sky.json")
    d = build()
    with open(out, "w") as fh:
        json.dump(d, fh, indent=2)
        fh.write("\n")
    print(f"wrote {out}: {len(d['panels'])} panels")
