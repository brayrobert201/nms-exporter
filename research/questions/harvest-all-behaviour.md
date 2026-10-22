---
type: Question
title: "What exactly does the Harvest All radius measure, and what does raising it cost?"
status: partial
asked: 2026-10-21
decides: "The value to use in a freighter Harvest All mod, and whether it is safe."
tags: [farming, freighter, modding]
runs: []
answered_by: [../../knowledge/mechanics/harvest-all-radius.md]
---

# What exactly does the Harvest All radius measure, and what does raising it cost?

## Why it matters

The value to use in a freighter Harvest All mod, and whether it is safe.

## Known so far

GcHarvestPlantAction Radius = 6.0 on the freighter hydroponic room floor and the Biodome (game-data, build 25800958). Unknown: centred where, sphere or cylinder (floors), whether it crosses rooms, performance cost of large values, why the mod page says it covers the whole freighter.

## Test set up (2026-10-23)

`scripts/nms-mod-harvest-all` installed radius 300 for Bob's freighter (1,549
plants over 156 x 163 m, two floors 8 m apart; farthest plant 223 m from any
planter slot). The first Harvest All with it shows whether the radius crosses
floors and rooms; the next save's plant timestamps show which plants it took.

## What would answer it

A game-data citation (`scripts/nms-pak`) for the values, plus a measurement or code evidence for the behaviour.
