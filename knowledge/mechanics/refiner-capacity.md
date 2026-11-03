---
type: Mechanic
title: Refiner slot caps - inputs by the stack-limit setting, a substance output stops at 4,095
status: draft
evidence_level: measured
builds: ["26308211"]
stale_after: next-build
sources:
  - research/sources/game-data/26308211/metadata/gamestate/difficultyconfig.MXML.L3845-3945.xml
  - research/sources/measurements/2026-10-30-corvette-refiner-cap.md
generated: {by: "machine:session", at: 2026-10-30}
verified: []
tags: [refining, save-format, corvette, freighter]
related: [../../research/questions/refiner-size-speed.md]
verdict: >
  A refiner's slots are a MaintenanceObject inventory: an input slot holds
  what the save's Inventory stack limits setting gives that group - 9,999
  substances on High, 250 on Normal, 150 on Low (products 10 / 10 / 5). A
  substance output stops at 4,095 whatever the refiner, and the game runs one
  more operation whenever the output is still below that, so a run ends at
  4,095 or up to yield - 1 past it. So the most product one load gives is the
  smaller of that and what a full load of every input yields, and the optimum
  load is as many operations as fit under both.
---

# Refiner slot caps

**An input slot holds the MaintenanceObject stack cap times the item's stack
multiplier: 9,999 of a substance under the High stack-limits setting (250
Normal, 150 Low), 10 of most products (5 on Low; Casing 20, Power Cells 200).
A substance output stops at 4,095 in every refiner; the last operation may
carry it just past (a 1 -> 2 recipe ends at 4,096).**

## Evidence

- `metadata/gamestate/difficultyconfig` carries, per Inventory stack limits
  option, a MaxSubstanceStackSizes and MaxProductStackSizes table by
  stack-size group; refiner containers in the save are StackSizeGroup
  MaintenanceObject (the same block holds the Personal, Ship, Freighter and
  Chest caps). Cited excerpt in the sources.
- The freighter's refiners in the live save (High setting) hold inputs up to
  9,969 in one slot, as the table says.
- Every product and substance in the reality tables carries a
  StackMultiplier (products: 1 for 1,293, 10 for 379, 5 for 305, up to
  1,000 for Ammo). The save's product slots show the group cap times it:
  in the exosuit (Personal, 10) Casing 20, Power Cells 200, milk 100; in the
  freighter (20) Casing 40, Frigate tokens 60; in a storage chest (20) Ammo
  9999, the ProductStackLimit. Refiner slots are the MaintenanceObject group
  (10 on High), so most products stop at 10 there.
- In game, a refiner's Paraffinium output will not go past 4,095 (player
  observation, 2026-10-30, on the freighter).
- The corvette refiner stopped with 4,096 Ferrite Dust out and 2,048 Rusted
  Metal left on a 1 -> 2 recipe: 2,048 operations from an empty output, the
  last one taken at 4,094 (below the cap) and finishing at 4,096. The save's
  MaxAmount reads 9999 there, so it is not what the game applies.

## What follows

- Operations before the output stops = ceil((4,095 - output) / yield) while
  the output is below 4,095. Max product per load = min(that, floor(min over
  inputs of input cap / amount per operation)) x yield. A 1 + 1 -> 2 recipe
  gives 4,096 after 2,048 operations (2,048 of each input); 1 + 1 -> 3 gives
  4,095 after 1,365; 3 -> 1 gives 3,333 from a full 9,999 input slot, short
  of the output cap.
- The optimum load is that many operations' worth of each input: more only
  strands input when the output stops first (the "full - empty it" state).
- The exporter (`nmsexporter/nms.py`, REFINER_OUTPUT_CAP,
  REFINER_STACK_LIMITS and CORVETTE_REFINER_CAP) reports the cap, the
  end-of-run output, the optimum load and what to add or take out per
  refiner.

## Not established

- Where the 4,095 is defined (not in the globals, the difficulty table or
  the refiner entities), and whether the corvette's input slots really hold
  4,096 or that was simply what was loaded: see the measurement source. Whether refiner size changes speed is a separate open
  question (related).
