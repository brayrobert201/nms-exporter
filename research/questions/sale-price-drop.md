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
