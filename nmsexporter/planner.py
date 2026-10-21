"""Device planner: how many of the high-value craftables the stock supports.

Answers the question asked of every save: "how many Stasis Devices or Fusion
Ignitors can I build right now, what blocks the next one, and what does the
next harvest add?" Blueprints come from the tables (items[id].craft), so the
tree is the game's own: intermediates are crafted recursively from stock,
never refined. Only known blueprints are used.

Standard library only; cheap enough to run on every save.
"""
from __future__ import annotations

import os

# The targets, in the order a greedy plan tries them. Both sell for the same
# base value, so the plan also tries the reverse order and keeps the better.
DEFAULT_TARGETS = [t for t in os.environ.get("NMS_PLAN_TARGETS", "ULTRAPROD1,ULTRAPROD2").split(",") if t]
MAX_PER_TARGET = 200
MAX_DEPTH = 6


class Planner:
    def __init__(self, items: dict, crops: dict):
        self.items = items
        self.crops = crops   # base part id -> {yield_id, amount, grow_seconds}

    def name(self, iid: str) -> str:
        return self.items.get(iid, {}).get("name", iid)

    def craft(self, iid: str, known: set) -> dict | None:
        rec = self.items.get(iid, {})
        c = rec.get("craft")
        return c if c and iid in known else None

    def _make(self, iid: str, n: int, stock: dict, known: set, depth: int, blocker: list) -> int:
        """Make up to n of iid from stock (mutated); returns how many were made.
        blocker collects the first raw ingredient that stopped the last attempt."""
        c = self.craft(iid, known)
        if not c:
            return 0
        made = 0
        for _ in range(n):
            snap = dict(stock)
            ok = True
            for ing in c["ingredients"]:
                need, have = ing["amount"], stock.get(ing["id"], 0)
                if have < need and depth < MAX_DEPTH and self.craft(ing["id"], known):
                    self._make(ing["id"], need - have, stock, known, depth + 1, blocker)
                    have = stock.get(ing["id"], 0)
                if have < need:
                    if not blocker:
                        blocker.append({"id": ing["id"], "item": self.name(ing["id"]), "have": have, "need": need})
                    ok = False
                    break
                stock[ing["id"]] = have - need
            if not ok:
                stock.clear()
                stock.update(snap)
                break
            stock[iid] = stock.get(iid, 0) + c.get("yield", 1)
            made += c.get("yield", 1)
        return made

    def _run(self, stock: dict, known: set, order: list) -> dict:
        st = dict(stock)
        counts, blockers = {}, {}
        for t in order:
            blk: list = []
            counts[t] = self._make(t, MAX_PER_TARGET, st, known, 0, blk)
            # The blocker of the *next* unit: retry once on the exhausted stock.
            blk = []
            self._make(t, 1, dict(st), known, 0, blk)
            blockers[t] = blk[0] if blk else None
        value = sum(counts[t] * self.items.get(t, {}).get("value", 0) for t in order)
        return {"order": list(order), "counts": counts, "names": {t: self.name(t) for t in order},
                "blockers": blockers, "value": value}

    def harvest(self, plants: dict) -> dict:
        """Everything one full harvest of the planted crops would add."""
        add: dict = {}
        for base in plants.values():
            for p in base.get("plants", []):
                crop = self.crops.get(p.get("id"))
                if crop and crop.get("yield_id"):
                    add[crop["yield_id"]] = add.get(crop["yield_id"], 0) + (crop.get("amount") or 0)
        return add

    def plan(self, stock: dict, known_products: list, plants: dict, targets: list | None = None) -> dict:
        targets = [t for t in (targets or DEFAULT_TARGETS) if t in self.items]
        known = set(known_products)
        orders = [targets] + ([list(reversed(targets))] if len(targets) > 1 else [])
        now = max((self._run(stock, known, o) for o in orders), key=lambda r: r["value"])
        add = self.harvest(plants)
        after_stock = dict(stock)
        for k, v in add.items():
            after_stock[k] = after_stock.get(k, 0) + v
        after = max((self._run(after_stock, known, o) for o in orders), key=lambda r: r["value"])
        per_target = []
        for t in targets:
            alone_now = self._run(stock, known, [t])
            alone_after = self._run(after_stock, known, [t])
            per_target.append({"id": t, "item": self.name(t), "value": self.items.get(t, {}).get("value", 0),
                               "now": alone_now["counts"][t], "after_harvest": alone_after["counts"][t],
                               "blocker": alone_now["blockers"][t], "blocker_after_harvest": alone_after["blockers"][t]})
        return {"targets": per_target, "best_now": now, "best_after_harvest": after,
                "harvest_adds": {self.name(k): v for k, v in sorted(add.items(), key=lambda kv: -kv[1])}}
