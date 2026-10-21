---
type: Question
title: "How much does each sale lower an item's price, and how fast does it recover?"
status: open
asked: 2026-10-21
decides: "How to batch device and Gold sales across systems; whether the planner should value stock below base price."
tags: [economy, trading]
runs: []
answered_by: []
---

# How much does each sale lower an item's price, and how fast does it recover?

## Why it matters

How to batch device and Gold sales across systems; whether the planner should value stock below base price.

## Known so far

Selling 89 devices at once averaged ~15.62M each against a 15.6M base (2026-10-21), so products may not drop at all per unit, or the system's band absorbed it. Substances are said to drop per sale. The per-sale drop formula is in code, not data (EconomyInfluenceMultiplier 0.25 is in the product table; UseTradingCostTable=false).

## What would answer it

Likely hardcoded: a runtime hook (pyMHF) or disassembly, or a careful measurement series stored under `research/sources/measurements/`.

## Measurement plan

**Products (next device run).** At one trade terminal, before selling, note
the displayed sell price of a Stasis Device (screenshot). Then sell **one** at a
time for the first five, a save after each; then batches of 5, 10 and the rest,
a save after each batch. Units delta / count per step gives the average price
per step; the screenshots give the displayed price.

**Substances (Gold).** Same terminal type, one system. Note the displayed Gold
price, then sell in batches of 1,000 with a save after each, ten batches
(10,000 Gold, ~3.5M). The curve of average price against cumulative quantity
is the per-sale drop. Then **recovery**: leave the system, come back after 1 h,
4 h and 24 h of real time (note whether the game was running), and sell another
1,000 each time with a save.

Record each time: system name withheld, its economy type and wealth (trade
terminal header or discovery page), station or planet terminal, and the time
of each save. Trigger a save at each step (enter your ship, or use a save point; the exporter picks up the new save within seconds). Read results with `curl -s 'localhost:9877/diff?against=1'` or `scripts/nms-rundown.py --diff`, and give the readings to a session to store under `research/sources/measurements/`.

Note: diffs that span the 22:44 save on 2026-10-21 show a false +4.29B units
(the history was stored before the wallet fix); compare saves after it.
