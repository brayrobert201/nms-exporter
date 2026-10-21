---
type: Mechanic
title: Extraction hotspots - classes, rates, ranges, gases and substances
status: draft
evidence_level: game-data
builds: ["25800958"]
stale_after: next-build
sources:
  - research/sources/game-data/25800958/metadata/simulation/scanning/regionhotspotstable.MXML.L1-355.xml
  - data/nms_tables.json#extraction
tags: [farming, extraction]
related: [../../research/questions/hotspot-minerals.md, ../../research/questions/extraction-network-falloff.md, ../../research/questions/hotspot-yield-distance.md]
generated: {by: "machine:session", at: 2026-10-21}
verified: []
---

# Extraction hotspots

**A single extractor on a class C mineral or gas hotspot makes 250 items/h; B,
A and S make 375, 500 and 625.** Ammonia is one of the 33 substances the game
lists as extractable from a hotspot.

## Evidence (REGIONHOTSPOTSTABLE and the base-building table)

- Six hotspot categories: Power, Mineral1-3, Gas1-2. Mineral and gas class
  odds C:B:A:S = 6:4:2:1 (minerals) and 20:4:2:1 (gases); class strength
  1 / 1.5 / 2 / 2.5. Power hotspots: strength 150 / 220 / 250 / 300.
- Extractor: 100 resource units/s, 1,440 units per item -> 250 items/h at
  strength 1; stores 250 items; a supply depot stores 1,000; 50 kP power.
- Gas1 by biome: Lush, Toxic, Blue, Swamp -> Nitrogen; Radioactive, Frozen,
  Green -> Radon; Scorched, Barren, Red, Lava -> Sulphurine; Waterworld, Gas
  Giant -> Methane; Dead and Weird -> Oxygen. Gas2 is always Oxygen.
- `RegionHotspotSubstances` (33 entries, each AmountCost 360,000 for a yield
  of 250): the five gases, the stellar metals and their activated forms,
  Pyrite, Paraffinium, **Ammonia (TOXIC1)**, Uranium, Dioxite, Phosphorus,
  Salt, Cobalt, Silver, Magnetised Ferrite, Rusted Metal, Gold, Sodium,
  Basalt, Faecium, Mordite, Crystallised Helium, Lithium.
- Falloff fields: `min_hotspot_falloff_distance_m` 100, `max_hotspot_falloff_distance_m`
  500, `max_hotspot_offset_distance_m` 150 (extracted to `data/nms_tables.json`).

## Scope and caveats

Rates are per extractor, before the pipe-network diminishing returns, which
are not in the data. Being in the extractable list says Ammonia *can* be a
hotspot substance; which substance a given planet's Mineral hotspots roll is
not in this table, and the save does not record it.

## Open

- [Which minerals a planet's hotspots can roll](../../research/questions/hotspot-minerals.md)
- [Network diminishing returns](../../research/questions/extraction-network-falloff.md)
- [How the falloff fields shape yield](../../research/questions/hotspot-yield-distance.md)
