#!/usr/bin/env python3
"""Generate the crafting dashboard: what can be made, and what is missing.

Usage: scripts/nms-grafana-crafting-dashboard.py [OUT.json]
Default output is ../grafana/no-mans-sky-crafting.json. Shares the panel
helpers (and palette) with nms-grafana-dashboard.py.
"""
import importlib.util
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("main_dash", os.path.join(HERE, "nms-grafana-dashboard.py"))
M = importlib.util.module_from_spec(spec)
spec.loader.exec_module(M)
target, stat, stats, table, timeseries, row, panel = M.target, M.stat, M.stats, M.table, M.timeseries, M.row, M.panel
DS, BLUE, INK2, GAUGE_CELL = M.DS, M.BLUE, M.INK2, M.GAUGE_CELL

# have per ingredient_id, re-labelled so it joins onto recipe rows
HAVE = 'sum by (ingredient_id) (label_replace(nms_item_total, "ingredient_id", "$1", "id", "(.*)"))'


def missing_expr(need):
    """clamp(need - have, 0) keeping ingredients with no stock at all."""
    return (f'clamp_min(({need}) - on (ingredient_id) group_left() '
            f'(({HAVE}) or on (ingredient_id) (0 * sum by (ingredient_id) ({need}))), 0)')


def build():
    P = []
    y = 0
    P.append(row("Overview", y)); y += 1
    P.append(stats("Blueprints", [
        dict(name="Known", expr='count(nms_craftable{known="1"})'),
        dict(name="Makeable now", expr='count(nms_craftable{known=~"$known"} > 0) or vector(0)'),
        dict(name="Blocked", expr='count(nms_craftable{known=~"$known"} == 0) or vector(0)'),
        dict(name="Selected: can make", expr='max(nms_craftable{item="$item"}) or vector(0)'),
    ], 0, y, 24, 4, description="Makeable counts intermediates you could craft from stock through routes you know"))
    y += 4
    P.append(table("What can I make now?", [
        target('nms_craftable{known=~"$known", route=~"$route"}', instant=True, ref="A", fmt="table"),
    ], 0, y, 24, 14, [("item", "Item"), ("Value", "Can make", "short"), ("route", "Via"), ("recipe", "Recipe")],
        sort=("Can make", True), extra_transforms=[{"id": "organize", "options": {"excludeByName": {"id": True, "known": True}}}],
        description="All levels: missing intermediates are crafted or refined from stock. Filter any column."))
    y += 14

    P.append(row("Selected item: $item × $qty", y)); y += 1
    need = 'nms_recipe_need{item="$item"} * on (id, route, recipe_id) group_left() ceil($qty / nms_recipe_yield{item="$item"})'
    P.append(table("Ingredients per route, for $qty", [
        target(need, instant=True, ref="A", fmt="table"),
        target(f'({need}) * 0 + on (ingredient_id) group_left() ({HAVE})', instant=True, ref="B", fmt="table"),
        target(missing_expr(need), instant=True, ref="C", fmt="table"),
    ], 0, y, 24, 10, [("route", "Via"), ("recipe", "Recipe"), ("ingredient", "Ingredient"), ("Value #A", "Need", "short"),
                      ("Value #B", "Have", "short"), ("Value #C", "Missing", "short"), ("recipe_known", "Known", None,
                       [{"id": "mappings", "value": [{"type": "value", "options": {"0": {"text": "no"}, "1": {"text": "yes"}}}]}])],
        sort=("Missing", True), description="One level: what each route needs directly. Have is the total across every container.",
        extra_transforms=[{"id": "organize", "options": {"excludeByName": {"id": True, "item": True, "known": True, "ingredient_id": True, "recipe_id": True}}}]))
    y += 10
    raw = 'nms_craft_raw_need{item="$item"} * $qty'
    P.append(table("Raw materials for $qty, every intermediate expanded", [
        target(raw, instant=True, ref="A", fmt="table"),
        target(f'({raw}) * 0 + on (ingredient_id) group_left() ({HAVE})', instant=True, ref="B", fmt="table"),
        target(missing_expr(raw), instant=True, ref="C", fmt="table"),
    ], 0, y, 24, 9, [("ingredient", "Raw material"), ("Value #A", "Need", "short"), ("Value #B", "Have", "short"), ("Value #C", "Missing", "short")],
        sort=("Missing", True),
        description="Products expand through their blueprint and refined substances through their recipe, choosing routes by what you hold. Ignores intermediates already in stock; the shortfall table below does not.",
        extra_transforms=[{"id": "organize", "options": {"excludeByName": {"id": True, "item": True, "known": True, "ingredient_id": True}}}]))
    y += 9
    P.append(table("Shortfall for one unit, using intermediates in stock", [
        target('nms_craft_shortfall{item="$item"}', instant=True, ref="A", fmt="table"),
    ], 0, y, 12, 8, [("ingredient", "Missing"), ("Value", "Amount", "short")], sort=("Amount", True),
        description="Exact for one unit: stock is drawn down level by level. Empty means you can make at least one now."))
    P.append(table("What uses $item", [
        target('nms_recipe_need{ingredient="$item"}', instant=True, ref="A", fmt="table"),
    ], 12, y, 12, 8, [("item", "Makes"), ("route", "Via"), ("recipe", "Recipe"), ("Value", "Per craft", "short")], sort=("Makes", False),
        extra_transforms=[{"id": "organize", "options": {"excludeByName": {"id": True, "known": True, "ingredient": True, "ingredient_id": True, "recipe_known": True, "recipe_id": True}}}]))
    y += 8
    P.append(timeseries("Can make over time: $item", [target('nms_craftable{item="$item"}', "{{item}} via {{route}}")], 0, y, 24, 7))
    y += 7

    P.append(row("Everything", y)); y += 1
    P.append(table("Every recipe", [
        target('nms_recipe_need{known=~"$known", route=~"$route"}', instant=True, ref="A", fmt="table"),
        target('nms_recipe_need{known=~"$known", route=~"$route"} * 0 + on (id, route, recipe_id) group_left() nms_recipe_yield{known=~"$known", route=~"$route"}', instant=True, ref="B", fmt="table"),
    ], 0, y, 24, 16, [("item", "Makes"), ("route", "Via"), ("recipe", "Recipe"), ("ingredient", "Ingredient"), ("Value #A", "Per craft", "short"),
                      ("Value #B", "Yield", "short"), ("recipe_known", "Known", None,
                       [{"id": "mappings", "value": [{"type": "value", "options": {"0": {"text": "no"}, "1": {"text": "yes"}}}]}])],
        sort=("Makes", False), description="Every crafting blueprint, refiner recipe and cooking recipe in the game, from the installed build's data files",
        extra_transforms=[{"id": "organize", "options": {"excludeByName": {"id": True, "known": True, "ingredient_id": True, "recipe_id": True}}}]))
    y += 16
    return {
        "uid": "no-mans-sky-crafting", "title": "No Man's Sky · Crafting", "tags": ["games", "no-mans-sky"], "editable": True,
        "schemaVersion": 39, "graphTooltip": 1, "fiscalYearStartMonth": 0, "timezone": "browser",
        "time": {"from": "now-3h", "to": "now"}, "refresh": "auto",
        "timepicker": {"refresh_intervals": ["auto", "15s", "30s", "1m", "5m", "15m"]},
        "links": [{"title": "No Man's Sky", "type": "link", "url": "/d/no-mans-sky", "icon": "dashboard", "keepTime": True}],
        "annotations": {"list": []},
        "description": "What can be made from stock, and what is missing. Computed by nms-exporter from the newest save and the game's own recipe tables.",
        "templating": {"list": [
            {"name": "item", "label": "Item", "type": "query", "datasource": DS, "query": {"query": "label_values(nms_craftable, item)", "refId": "v"},
             "definition": "label_values(nms_craftable, item)", "multi": False, "includeAll": False,
             "current": {"text": "Warp Cell", "value": "Warp Cell"}, "refresh": 2, "sort": 1, "options": []},
            {"name": "qty", "label": "Quantity", "type": "textbox", "query": "1", "current": {"text": "1", "value": "1"}, "options": [{"text": "1", "value": "1", "selected": True}]},
            {"name": "known", "label": "Blueprints", "type": "custom", "query": "known : 1, all : .*", "multi": False, "includeAll": False,
             "current": {"text": "known", "value": "1"}, "options": [{"text": "known", "value": "1", "selected": True}, {"text": "all", "value": ".*", "selected": False}]},
            {"name": "route", "label": "Via", "type": "custom", "query": "any : .*, craft : craft, refine : refine, cook : cook", "multi": False, "includeAll": False,
             "current": {"text": "any", "value": ".*"}, "options": [{"text": "any", "value": ".*", "selected": True}, {"text": "craft", "value": "craft", "selected": False},
                                                                   {"text": "refine", "value": "refine", "selected": False}, {"text": "cook", "value": "cook", "selected": False}]},
        ]},
        "panels": P,
    }


if __name__ == "__main__":
    out = sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, "..", "grafana", "no-mans-sky-crafting.json")
    d = build()
    with open(out, "w") as fh:
        json.dump(d, fh, indent=2)
        fh.write("\n")
    print(f"wrote {out}: {len(d['panels'])} panels")
