---
type: Question
title: "What is the formula for diminishing returns when extractors share a pipe network?"
status: partial
asked: 2026-10-21
decides: "Farm layout: how many extractors per network and how many networks per hotspot."
tags: [farming, extraction]
runs: []
answered_by: []
---

# What is the formula for diminishing returns when extractors share a pipe network?

## Why it matters

Farm layout: how many extractors per network and how many networks per hotspot.

## Known so far

Bob measured a standalone extractor at 300/h dropping to 200/h once piped in. Not in the data tables. Community thresholds of 1,000-2,500/h per network are unsourced.

## What would answer it

Likely hardcoded: a runtime hook (pyMHF) or disassembly, or a careful measurement series stored under `research/sources/measurements/`.

## Measurement plan

Your existing farms already suggest a per-network ceiling around 1,000-1,500
items/h regardless of extractor count (see
`research/sources/measurements/2026-10-21-network-rates-cross-section.md`), but
hotspot class is uncontrolled. To get the formula, use **one hotspot**:

1. Pick an unused mineral hotspot; note its class and the survey percentage at
   the spot (screenshot).
2. Build one extractor within ~50u of the centre, with its own depot and
   power, no pipe to anything else. Leave it 2 h, saving at the start and end.
3. Add a second extractor **piped** to the first. 2 h, saves at both ends.
4. Repeat up to six extractors, one per step.
5. Control: add one more extractor on the same hotspot that is **not** piped,
   with its own depot. If it keeps its full standalone rate while the network
   is slowed, the falloff is per network; if it slows too, it is per hotspot.

The exporter splits networks by pipes and measures each from consecutive
saves; extractor positions come from the save. Trigger a save at each step (enter your ship, or use a save point; the exporter picks up the new save within seconds). Read results with `curl -s 'localhost:9877/diff?against=1'` or `scripts/nms-rundown.py --diff`, and give the readings to a session to store under `research/sources/measurements/`.
