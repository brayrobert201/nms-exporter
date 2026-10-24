"""What can be made from what is in stock.

Routes come from the game tables: crafting blueprints (a product's
Requirements), refiner recipes and cooking recipes. Against the inventory
totals this answers, per item:

  direct     one level: units makeable now from stock alone, per route
  makeable   all levels: units makeable now, crafting missing intermediates
             from stock through the blueprints the player knows (refiner and
             cooking recipes need no discovery, so they always count)
  raw_need   raw materials per unit with every intermediate expanded
  shortfall  raw materials missing to make one unit, using intermediates in stock

The multi-level search is a simulation on a copy of the inventory, so shared
bottlenecks (chromatic metal feeding two branches) are accounted for.
"""
from __future__ import annotations

import math
from collections import defaultdict

MAX_DEPTH = 6
MAX_UNITS = 1_000_000

# Substances expand through refiner recipes like anything else when one exists
# (Star Bulb from Paraffinium and Nitrogen, Cactus Flesh from Pyrite and
# Sulphurine ...); only substances with no recipe at all are leaves. Recipes
# that need the substance itself as a seed are skipped by the loop guard.
REFINED_SUBSTANCES = {"STELLAR2", "FUEL2", "LAND2", "LAND3", "CATALYST2", "ROCKETSUB", "WATER2"}   # kept for reference


class Crafting:
    def __init__(self, tables: dict):
        self.items = tables.get("items", {})
        self.routes: dict[str, list] = defaultdict(list)
        for iid, it in self.items.items():
            c = it.get("craft")
            if c:
                self.routes[iid].append({"route": "craft", "recipe": "Craft", "recipe_id": iid, "yield": c["yield"],
                                         "needs": [(i["id"], i["amount"]) for i in c["ingredients"]]})
        for r in tables.get("recipes", []):
            self.routes[r["result"]["id"]].append({
                "route": "cook" if r["cooking"] else "refine", "recipe": r["operation"] or r["id"], "recipe_id": r["id"],
                "yield": r["result"]["amount"], "needs": [(i["id"], i["amount"]) for i in r["ingredients"]]})

    def name(self, iid: str) -> str:
        return self.items.get(iid, {}).get("name") or iid

    # -- per save --------------------------------------------------------------
    def usable(self, known_products: set, known_recipes: set, known_only: bool = True) -> tuple[dict, dict]:
        """(routes, usable): every route per item marked known or not, and the ones that may be used.
        Crafting needs the blueprint; a refiner or nutrient processor runs any recipe
        whether or not the player has "discovered" it, so those are always usable."""
        def is_known(iid, r):
            return iid in known_products if r["route"] == "craft" else r["recipe_id"] in known_recipes

        routes = {iid: [dict(r, known=is_known(iid, r)) for r in rs] for iid, rs in self.routes.items()}
        usable = {iid: [r for r in rs if r["known"] or not known_only or r["route"] != "craft"]
                  for iid, rs in routes.items()}
        return routes, usable

    @staticmethod
    def direct(r, inv) -> int:
        """Units one level of route r makes from inv alone."""
        n = None
        for ing, amt in r["needs"]:
            k = inv.get(ing, 0) // amt if amt else 0
            n = k if n is None else min(n, k)
        return (n or 0) * r["yield"]

    @classmethod
    def pick(cls, usable: dict, iid, inv, stack, pref=None):
        """Best route for iid: most feasible from `pref` (default: the working inventory),
        crafting on ties, then the fewest ingredients."""
        best, best_key = None, None
        for r in usable.get(iid, []):
            if any(ing in stack for ing, _ in r["needs"]):
                continue                       # would loop (e.g. Oxygenate Carbon feeds itself)
            key = (cls.direct(r, pref if pref is not None else inv), r["route"] == "craft", -len(r["needs"]))
            if best is None or key > best_key:
                best, best_key = r, key
        return best

    def tree(self, targets: list, stock: dict, known_products: set, known_recipes: set) -> dict:
        """Every level of making targets [(item_id, qty), ...] from stock, as the search does it, plus the
        same work as a bottom-up build order.

        Each node takes what stock holds first (a shared copy, so an ingredient used twice, or by two
        targets, is only counted once) and makes the rest through the chosen route; a leaf with no
        route left is a shortfall. The targets themselves are always made, never taken from stock.
        Node: id, item, need, have (stock before this node drew on it), from_stock, make (units made),
        crafts, route, recipe, recipe_id, yield, needs (per craft), short, children.

        steps: the build order. An item's step is its longest distance from raw materials (anything
        taken from stock or short counts as raw), so everything in a step can be made once the steps
        before it are done. Each entry sums every place the item is made."""
        _, usable = self.usable(known_products, known_recipes)
        inv = dict(stock)

        def node(nid, need, depth, stack):
            have = inv.get(nid, 0)
            take = min(have, need) if depth else 0      # a target is always made, never taken
            inv[nid] = have - take
            n = {"id": nid, "item": self.name(nid), "need": need, "have": have, "from_stock": take, "make": 0,
                 "crafts": 0, "route": None, "recipe": None, "recipe_id": None, "yield": None, "needs": [], "short": 0,
                 "children": []}
            rest = need - take
            if rest <= 0:
                return n
            r = self.pick(usable, nid, inv, stack) if depth < MAX_DEPTH and usable.get(nid) else None
            if r is None:
                n["short"] = rest
                return n
            crafts = math.ceil(rest / r["yield"])
            n.update(make=crafts * r["yield"], crafts=crafts, route=r["route"], recipe=r["recipe"], recipe_id=r["recipe_id"],
                     needs=[{"id": i, "item": self.name(i), "amount": a} for i, a in r["needs"]], **{"yield": r["yield"]})
            stack = stack | {nid}
            n["children"] = [node(ing, amt * crafts, depth + 1, stack) for ing, amt in r["needs"]]
            # a surplus from rounding up to whole crafts goes back to stock for later branches
            inv[nid] = inv.get(nid, 0) + crafts * r["yield"] - rest
            return n

        roots = [node(iid, max(1, int(q)), 0, frozenset()) for iid, q in targets]
        raw: dict = {}
        short: dict = {}
        made: dict = {}
        level: dict = {}

        def walk(n) -> int:
            """Fold one node into the totals; returns its distance from raw materials."""
            if n["from_stock"] and not n["children"]:
                raw[n["id"]] = raw.get(n["id"], 0) + n["from_stock"]
            if n["short"]:
                short[n["id"]] = short.get(n["id"], 0) + n["short"]
            if not n["children"]:
                return 0
            d = 1 + max(walk(ch) for ch in n["children"])
            key = (n["id"], n["recipe_id"])
            m = made.setdefault(key, {"id": n["id"], "item": n["item"], "route": n["route"], "recipe": n["recipe"],
                                      "recipe_id": n["recipe_id"], "yield": n["yield"], "needs": n["needs"], "make": 0,
                                      "crafts": 0, "need": 0, "from_stock": 0, "have": stock.get(n["id"], 0),
                                      "target": False})
            m["make"] += n["make"]; m["crafts"] += n["crafts"]; m["need"] += n["need"]; m["from_stock"] += n["from_stock"]
            level[key] = max(level.get(key, 0), d)
            return d
        for r in roots:
            walk(r)
        for iid, _ in targets:
            for key, m in made.items():
                if m["id"] == iid:
                    m["target"] = True
        # the targets are the last step, together, whatever their depth: the order ends with what was asked for
        last = 1 + max((v for k, v in level.items() if not made[k]["target"]), default=0)
        for key, m in made.items():
            if m["target"]:
                level[key] = last
        steps: dict = {}
        for key, m in made.items():
            steps.setdefault(level[key], []).append(m)
        step_list = [{"step": i + 1, "items": sorted(steps[lv], key=lambda m: (m["target"], -m["make"], m["item"]))}
                     for i, lv in enumerate(sorted(steps))]
        items = lambda dd: [{"id": k, "item": self.name(k), "amount": v, "have": stock.get(k, 0)}
                            for k, v in sorted(dd.items(), key=lambda kv: -kv[1])]
        return {"targets": [{"id": iid, "item": self.name(iid), "qty": max(1, int(q))} for iid, q in targets],
                "trees": roots, "steps": step_list, "ok": not short, "raw": items(raw), "short": items(short)}

    def evaluate(self, stock: dict, known_products: set, known_recipes: set, known_only: bool = True,
                 consume: tuple | None = None) -> dict:
        """stock: {item_id: amount}. Returns per-item results plus the route list.
        With consume=(item_id, n) it instead returns the stock left after making n
        of that item through the same route choices, or None if that is not possible."""
        routes, usable = self.usable(known_products, known_recipes, known_only)
        direct = self.direct

        def pick(iid, inv, stack, pref=None):
            return self.pick(usable, iid, inv, stack, pref)

        def is_leaf(iid):
            return not usable.get(iid)

        def expand(iid, qty, inv, shortfall, depth, stack, pref=None):
            take = min(inv.get(iid, 0), qty)
            if take:
                inv[iid] -= take
                qty -= take
            if qty <= 0:
                return
            r = pick(iid, inv, stack, pref) if depth < MAX_DEPTH and not is_leaf(iid) else None
            if r is None:
                shortfall[iid] += qty
                return
            crafts = math.ceil(qty / r["yield"])
            stack.add(iid)
            for ing, amt in r["needs"]:
                expand(ing, amt * crafts, inv, shortfall, depth + 1, stack, pref)
            stack.discard(iid)

        def feasible(iid, n):
            inv = dict(stock)
            short = defaultdict(int)
            expand(iid, n, inv, short, 0, set())
            return not short

        def makeable(iid):
            if not usable.get(iid) or not feasible(iid, 1):
                return 0
            lo, hi = 1, 2
            while hi <= MAX_UNITS and feasible(iid, hi):
                lo, hi = hi, hi * 2
            hi = min(hi, MAX_UNITS)
            while lo < hi - 1:
                mid = (lo + hi) // 2
                if feasible(iid, mid):
                    lo = mid
                else:
                    hi = mid
            return lo

        if consume is not None:
            # Just spend the stock on `n` units of one item and hand the rest back.
            iid, n = consume
            inv = dict(stock)
            short = defaultdict(int)
            expand(iid, n, inv, short, 0, set())
            return None if short else inv

        out = {}
        for iid, rs in routes.items():
            if not rs:
                continue
            inv0 = dict(stock)
            res = {"id": iid, "item": self.name(iid), "known": any(r["known"] for r in rs),
                   "routes": [dict(r, direct=direct(r, inv0)) for r in rs]}
            chosen = pick(iid, dict(stock), set())
            res["best_route"] = chosen["route"] if chosen else None
            res["best_recipe"] = chosen["recipe"] if chosen else None
            res["makeable"] = makeable(iid) if usable.get(iid) else 0
            # stock-independent raw need per unit, and exact shortfall for one unit
            raw = defaultdict(int)
            expand(iid, 1, {}, raw, 0, set(), pref=stock)   # routes chosen by what is actually held
            res["raw_need"] = dict(raw)
            short = defaultdict(int)
            expand(iid, 1, dict(stock), short, 0, set())
            res["shortfall"] = dict(short)
            out[iid] = res
        return out
