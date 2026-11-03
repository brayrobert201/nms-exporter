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
TREE_DEPTH = 12     # the build tree blocks loops by its ancestor stack, so it can go deeper than the search
MAX_UNITS = 1_000_000

# Substances expand through refiner recipes like anything else when one exists
# (Star Bulb from Paraffinium and Nitrogen, Cactus Flesh from Pyrite and
# Sulphurine ...); only substances with no recipe at all are leaves. Recipes
# that need the substance itself as a seed are skipped by the loop guard.
REFINED_SUBSTANCES = {"STELLAR2", "FUEL2", "LAND2", "LAND3", "CATALYST2", "ROCKETSUB", "WATER2"}   # kept for reference

# Refiner slot caps (knowledge/mechanics/refiner-capacity.md). A refiner's slots are a
# MaintenanceObject inventory, so each holds what the save's "Inventory stack limits"
# setting gives that group (substances, products) times the item's own StackMultiplier
# (items.<id>.stack; Casing 2, Power Cells 20, most 1), never past STACK_LIMIT. A substance
# output stops at REFINER_OUTPUT_CAP, and the game runs one more operation whenever the
# output is still below that, so a run ends at the cap or up to yield - 1 past it.
REFINER_STACK_LIMITS = {"High": (9999, 10), "Normal": (250, 10), "Low": (150, 5)}
STACK_LIMIT = 9999
REFINER_OUTPUT_CAP = 4095
CORVETTE_REFINER_CAP = 4096     # the corvette refiner wall's input slots, as loaded in a save
MODES = ("max", "fast", "now")  # route ranking: most from stock, instant crafting first, or crafting only


def ops_to_cap(output: int, cap: int, per_op: int) -> int:
    """Operations a refiner still runs before its output stops: one more whenever the
    output is below the cap, so the last may carry it past (4095 -> 4096 on a 1 -> 2)."""
    if not cap or not per_op or output >= cap:
        return 0
    return -(-(cap - output) // per_op)


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
                "yield": r["result"]["amount"], "needs": [(i["id"], i["amount"]) for i in r["ingredients"]],
                "seconds_per_op": r.get("seconds_per_op") or 0})

    def slot_cap(self, iid: str, setting: str = "High", output: bool = False, corvette: bool = False) -> int:
        """What a refiner slot holds of iid (see the constants above)."""
        sub_cap, prod_cap = REFINER_STACK_LIMITS.get(setting, REFINER_STACK_LIMITS["High"])
        it = self.items.get(iid, {})
        mult = it.get("stack") or 1
        if it.get("type") == "Substance":
            cap = min(STACK_LIMIT, int((CORVETTE_REFINER_CAP if corvette else sub_cap) * mult))
            return min(cap, REFINER_OUTPUT_CAP) if output else cap
        return min(STACK_LIMIT, int(prod_cap * mult))

    def load_ops(self, r: dict, iid: str, setting: str = "High") -> int:
        """Operations one full load of a refiner (or nutrient processor) recipe runs: every input
        slot filled, the output stopping at its cap."""
        if r["route"] == "craft":
            return 0
        ops = ops_to_cap(0, self.slot_cap(iid, setting, output=True), r["yield"] or 1)
        for ing, amt in r["needs"]:
            if amt:
                ops = min(ops, self.slot_cap(ing, setting) // amt)
        return max(1, ops)

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

    def tree(self, targets: list, stock: dict, known_products: set, known_recipes: set,
             mode: str = "max", refiners: int = 1, setting: str = "High", compare: list | None = None,
             pins: dict | None = None, choices: dict | None = None) -> dict:
        """Every level of making targets [(item_id, qty), ...] together from stock, and the same work as a
        bottom-up build order.

        Routes are ranked once per item against the starting stock (mode "max": most it makes from stock
        alone, crafting on ties, then fewest ingredients; mode "fast": crafting, which is instant, before
        cooking before refining, then most from stock; mode "now": crafting only, what can be made this
        minute from what is held), so the choice does not flip as quantities change. `pins`
        ({item id: [recipe ids]}) puts those recipes first for that item, in that order, ahead of the
        ranking, so a plan stays on the same paths as stock changes from save to save. `choices`
        ({item id: "craft" | "refine" | "cook"}) keeps an item to that kind of route, the player's
        call on the Build page; an item with no route of that kind, and "now" (crafting only), ignore it.
        A node takes what earlier crafts left over first, then stock, then makes the rest: as many as
        the first route can make, the remainder by the next, and so on. Only when no route can finish
        does the remainder go to the route with the smallest shortfall, whose missing leaves are short.
        Stock is a shared copy, so an ingredient used by two branches or two targets is counted once.

        Node: id, item, need, have (stock at the start), from_stock, from_made (leftovers of earlier
        crafts), make, short, ways [{route, recipe, recipe_id, yield, crafts, make, needs, children}].
        steps: the build order. An item's step is its longest distance from raw materials, so all of a
        step can be made once the steps before it are done; the targets are the last step. Each step
        entry sums every place the item is made, per way, and lists every route that makes it.

        `time` is what the refining and cooking take: every way carries its seconds (operations x the
        recipe's seconds per operation) and its loads (a refiner holds one optimum load at a time, see
        load_ops); each step's loads are dealt out over `refiners` longest-first, steps run one after
        another (a step's inputs come from the step before), and crafting is instant. `compare` lists
        other refiner counts to time the same work at (time.by_refiners), to show what more would save."""
        routes_all, usable = self.usable(known_products, known_recipes)
        rank_cache: dict = {}
        speed = {"craft": 0, "cook": 1, "refine": 2}

        def ranked(iid):
            if iid not in rank_cache:
                rs = usable.get(iid, [])
                if mode == "now":
                    rs = [r for r in rs if r["route"] == "craft"]
                ch = (choices or {}).get(iid)
                if ch and mode != "now" and any(r["route"] == ch for r in rs):
                    rs = [r for r in rs if r["route"] == ch]
                if mode == "fast":
                    key = lambda r: (speed.get(r["route"], 3), -self.direct(r, stock), len(r["needs"]))
                else:
                    key = lambda r: (-self.direct(r, stock), r["route"] != "craft", len(r["needs"]))
                rs = sorted(rs, key=key)
                pinned = (pins or {}).get(iid) or []
                if pinned:         # a stable sort: the pinned recipes first in their order, the rest as ranked
                    order = {rid: i for i, rid in enumerate(pinned)}
                    rs = sorted(rs, key=lambda r: order.get(r["recipe_id"], len(order)))
                rank_cache[iid] = rs
            return rank_cache[iid]

        def routes_for(iid, stack):
            return [r for r in ranked(iid) if not any(ing in stack for ing, _ in r["needs"])] if len(stack) < TREE_DEPTH else []

        def trial(iid, qty, inv, made, stack) -> int:
            """Units short if qty of iid were made the simple way (first route that fits at each level).
            Mutates inv/made: callers pass copies."""
            t = min(made.get(iid, 0), qty); made[iid] = made.get(iid, 0) - t; qty -= t
            t = min(inv.get(iid, 0), qty); inv[iid] = inv.get(iid, 0) - t; qty -= t
            if qty <= 0:
                return 0
            rs = routes_for(iid, stack)
            if not rs:
                return qty
            r = rs[0]
            crafts = math.ceil(qty / r["yield"])
            short = sum(trial(ing, amt * crafts, inv, made, stack | {iid}) for ing, amt in r["needs"])
            made[iid] = made.get(iid, 0) + crafts * r["yield"] - qty
            return short

        def fits(r, crafts, inv, made, stack) -> bool:
            i2, m2 = dict(inv), dict(made)
            return all(trial(ing, amt * crafts, i2, m2, stack) == 0 for ing, amt in r["needs"])

        inv, made = dict(stock), {}

        def node(nid, need, depth, stack):
            n = {"id": nid, "item": self.name(nid), "need": need, "have": stock.get(nid, 0), "from_stock": 0,
                 "from_made": 0, "make": 0, "short": 0, "ways": []}
            rest = need
            if depth:                                   # a target is always made, never taken
                t = min(made.get(nid, 0), rest); made[nid] = made.get(nid, 0) - t; rest -= t; n["from_made"] = t
                t = min(inv.get(nid, 0), rest); inv[nid] = inv.get(nid, 0) - t; rest -= t; n["from_stock"] = t
            if rest <= 0:
                return n
            sub = stack | {nid}
            rs = routes_for(nid, stack)

            def build(r, crafts):
                way = {"route": r["route"], "recipe": r["recipe"], "recipe_id": r["recipe_id"], "yield": r["yield"],
                       "crafts": crafts, "make": crafts * r["yield"],
                       "seconds": crafts * (r.get("seconds_per_op") or 0),
                       "loads": math.ceil(crafts / self.load_ops(r, nid, setting)) if r["route"] != "craft" else 0,
                       "needs": [{"id": i, "item": self.name(i), "amount": a} for i, a in r["needs"]]}
                way["children"] = [node(ing, amt * crafts, depth + 1, sub) for ing, amt in r["needs"]]
                n["ways"].append(way)
                return crafts * r["yield"]

            for r in rs:
                if rest <= 0:
                    break
                want = math.ceil(rest / r["yield"])
                if fits(r, want, inv, made, sub):
                    k = want
                else:                                   # the most this route can make: fits(lo), not fits(hi)
                    lo, hi = 0, want
                    while hi - lo > 1:
                        mid = (lo + hi) // 2
                        lo, hi = (mid, hi) if fits(r, mid, inv, made, sub) else (lo, mid)
                    k = lo
                if k:
                    got = build(r, k)
                    made[nid] = made.get(nid, 0) + max(0, got - rest)
                    rest -= got
            if rest > 0 and rs:
                # nothing finishes it: the route that leaves the least missing takes the remainder
                def short_of(r):
                    i2, m2 = dict(inv), dict(made)
                    c = math.ceil(rest / r["yield"])
                    return sum(trial(ing, amt * c, i2, m2, sub) for ing, amt in r["needs"])
                r = min(rs, key=short_of)
                got = build(r, math.ceil(rest / r["yield"]))
                made[nid] = made.get(nid, 0) + max(0, got - rest)
                rest -= got
            if rest > 0:
                n["short"] = rest
            n["make"] = sum(w["make"] for w in n["ways"])
            return n

        roots = [node(iid, max(1, int(q)), 0, frozenset()) for iid, q in targets]
        target_ids = {iid for iid, _ in targets}
        raw: dict = {}
        short: dict = {}
        agg: dict = {}
        level: dict = {}

        def walk(n) -> int:
            """Fold one node into the totals; returns its distance from raw materials."""
            if n["short"]:
                short[n["id"]] = short.get(n["id"], 0) + n["short"]
            if not n["ways"]:
                if n["from_stock"]:
                    raw[n["id"]] = raw.get(n["id"], 0) + n["from_stock"]
                return 0
            d = 1 + max((walk(ch) for w in n["ways"] for ch in w["children"]), default=0)
            a = agg.setdefault(n["id"], {"id": n["id"], "item": n["item"], "make": 0, "need": 0, "from_stock": 0,
                                         "from_made": 0, "have": stock.get(n["id"], 0), "ways": {}, "target": n["id"] in target_ids})
            for k in ("make", "need", "from_stock", "from_made"):
                a[k] += n[k]
            for w in n["ways"]:
                aw = a["ways"].setdefault(w["recipe_id"], {k: w[k] for k in ("route", "recipe", "recipe_id", "yield", "needs")} | {"crafts": 0, "make": 0, "seconds": 0, "loads": 0})
                aw["crafts"] += w["crafts"]; aw["make"] += w["make"]; aw["seconds"] += w["seconds"]; aw["loads"] += w["loads"]
            level[n["id"]] = max(level.get(n["id"], 0), d)
            return d
        for r in roots:
            walk(r)
        last = 1 + max((v for k, v in level.items() if k not in target_ids), default=0)
        for k in level:
            if k in target_ids:
                level[k] = last
        steps: dict = {}
        for iid, a in agg.items():
            used = a["ways"]
            a["ways"] = sorted(used.values(), key=lambda w: -w["make"])
            # every route that makes it, used or not: what each needs and what it makes from stock alone
            a["all_ways"] = [{"route": r["route"], "recipe": r["recipe"], "recipe_id": r["recipe_id"], "yield": r["yield"],
                              "known": r["known"], "used": used.get(r["recipe_id"], {}).get("crafts", 0),
                              "from_stock_alone": self.direct(r, stock),
                              "needs": [{"id": i, "item": self.name(i), "amount": am, "have": stock.get(i, 0)} for i, am in r["needs"]]}
                             for r in routes_all.get(iid, [])]
            a["all_ways"].sort(key=lambda w: (-w["used"], not w["known"], -w["from_stock_alone"]))
            # the kinds of route the player can choose between here (crafting only with the blueprint known)
            a["kinds"] = sorted({r["route"] for r in usable.get(iid, [])})
            a["choice"] = (choices or {}).get(iid)
            steps.setdefault(level[iid], []).append(a)
        step_list = [{"step": i + 1, "items": sorted(steps[lv], key=lambda m: (m["target"], -m["make"], m["item"]))}
                     for i, lv in enumerate(sorted(steps))]
        time = self.schedule(step_list, refiners)
        time["by_refiners"] = [{"refiners": n, "wall_seconds": self.schedule(step_list, n)["wall_seconds"]}
                               for n in sorted({int(n) for n in (compare or []) if n} | {int(refiners)})]
        items = lambda dd: [{"id": k, "item": self.name(k), "amount": v, "have": stock.get(k, 0)}
                            for k, v in sorted(dd.items(), key=lambda kv: -kv[1])]
        pinned_items = sorted(iid for iid, a in agg.items()
                              if any(w["recipe_id"] in ((pins or {}).get(iid) or []) for w in a["ways"]))
        return {"targets": [{"id": iid, "item": self.name(iid), "qty": max(1, int(q))} for iid, q in targets],
                "trees": roots, "steps": step_list, "ok": not short, "raw": items(raw), "short": items(short),
                "mode": mode, "time": time, "pinned_items": pinned_items}

    @staticmethod
    def schedule(steps: list, refiners: int) -> dict:
        """How long the refining and cooking in a build order take. Each refine way is loads of
        seconds / loads each; a step's loads go to the least busy of `refiners` refiners, longest
        first, and the steps run in turn. Cooking is counted on one nutrient processor. Crafting
        is instant. Loading and emptying time is the player's and not counted."""
        refiners = max(1, int(refiners or 1))
        total = {"refine_seconds": 0, "cook_seconds": 0, "crafts": 0, "refiner_ops": 0, "cook_ops": 0,
                 "loads": 0, "refiners": refiners, "wall_seconds": 0, "steps": []}
        for st in steps:
            lanes = [0.0] * refiners
            cook = 0.0
            jobs = []
            for m in st["items"]:
                for w in m["ways"]:
                    if w["route"] == "craft":
                        total["crafts"] += w["crafts"]
                        continue
                    if w["route"] == "cook":
                        total["cook_seconds"] += w["seconds"]; total["cook_ops"] += w["crafts"]; cook += w["seconds"]
                        continue
                    total["refine_seconds"] += w["seconds"]; total["refiner_ops"] += w["crafts"]; total["loads"] += w["loads"]
                    per = w["seconds"] / w["loads"] if w["loads"] else 0
                    jobs += [per] * w["loads"]
            for j in sorted(jobs, reverse=True):
                i = min(range(refiners), key=lambda k: lanes[k])
                lanes[i] += j
            wall = max(max(lanes), cook)
            total["wall_seconds"] += wall
            total["steps"].append({"step": st["step"], "wall_seconds": wall, "loads": len(jobs)})
        total["instant"] = total["refine_seconds"] == 0 and total["cook_seconds"] == 0
        return total

    def most(self, iid: str, stock: dict, known_products: set, known_recipes: set, cap: int = 10_000,
             hint: int | None = None, mode: str = "max", pins: dict | None = None, choices: dict | None = None) -> int:
        """The most of iid the build tree makes from stock (every route, split as tree() splits), up to cap,
        in the given mode ("now" is what crafting alone makes this minute) and on the pinned paths.
        Units already held are not counted: the tree always makes the item asked for. A hint (say the
        search's count less what is held) starts the search near the answer."""
        ok = lambda n: self.tree([(iid, n)], stock, known_products, known_recipes, mode=mode, pins=pins, choices=choices)["ok"]
        lo, hi = 0, None                     # ok(lo), not ok(hi)
        if hint:
            h = max(1, min(int(hint), cap))
            if ok(h):
                lo = h
            else:
                hi = h
        if hi is None:
            if lo >= cap:
                return cap
            step = max(1, lo)
            while True:
                nxt = min(lo + step, cap)
                if not ok(nxt):
                    hi = nxt
                    break
                lo = nxt
                if lo >= cap:
                    return cap
                step *= 2
        while hi - lo > 1:
            mid = (lo + hi) // 2
            lo, hi = (mid, hi) if ok(mid) else (lo, mid)
        return lo

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
