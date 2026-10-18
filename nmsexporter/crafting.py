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
    def evaluate(self, stock: dict, known_products: set, known_recipes: set, known_only: bool = True) -> dict:
        """stock: {item_id: amount}. Returns per-item results plus the route list."""
        def is_known(iid, r):
            return iid in known_products if r["route"] == "craft" else r["recipe_id"] in known_recipes

        routes = {}
        for iid, rs in self.routes.items():
            routes[iid] = [dict(r, known=is_known(iid, r)) for r in rs]
        # Crafting needs the blueprint; a refiner or nutrient processor runs any recipe
        # whether or not the player has "discovered" it, so those are always usable.
        usable = {iid: [r for r in rs if r["known"] or not known_only or r["route"] != "craft"]
                  for iid, rs in routes.items()}

        def direct(r, inv):
            n = None
            for ing, amt in r["needs"]:
                k = inv.get(ing, 0) // amt if amt else 0
                n = k if n is None else min(n, k)
            return (n or 0) * r["yield"]

        def pick(iid, inv, stack, pref=None):
            """Best route for iid: most feasible from `pref` (default: the working inventory),
            crafting on ties, then the fewest ingredients."""
            best, best_key = None, None
            for r in usable.get(iid, []):
                if any(ing in stack for ing, _ in r["needs"]):
                    continue                       # would loop (e.g. Oxygenate Carbon feeds itself)
                key = (direct(r, pref if pref is not None else inv), r["route"] == "craft", -len(r["needs"]))
                if best is None or key > best_key:
                    best, best_key = r, key
            return best

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
