---
type: Mechanic
title: Base power - part ratings, battery charge in the save, what the save omits
status: draft
evidence_level: game-data
builds: ["25800958"]
stale_after: next-build
sources:
  - data/nms_tables.json#buildings
  - data/nms_tables.json#extraction
generated: {by: "machine:session", at: 2026-10-22}
verified: []
tags: [power, farming, save-format]
related: [extraction-hotspots.md, save-coordinates.md]
verdict: >
  An extractor needs 50 kP; an electromagnetic generator makes 150/220/250/300 kP
  on a class C/B/A/S power hotspot; solar 50 kP by day; a fuelled biofuel
  generator 50 kP; a battery stores 45,000. The save holds each battery's charge
  but not hotspot class, biofuel fuel, or a traceable wire graph.
---

# Base power

**An extractor needs 50 kP to run; an electromagnetic generator gives 1 x its
power hotspot's strength (150 / 220 / 250 / 300 kP for C / B / A / S); solar
gives 50 kP by day; a biofuel generator gives 50 kP while it burns 1 fuel unit/s
(holds 180,000); a battery stores 45,000.**

## Evidence

- Base-building table (data/nms_tables.json `buildings`): U_EXTRACTOR_S and
  U_GASEXTRACTOR depend on Power -50 with effect EnablesRate; U_SOLAR_S Power 50,
  DayNight; U_GENERATOR_S Power rate 1 on a Power hotspot; U_BIOGENERATOR is on
  the Fuel network (-1/s, storage 180000) and adds Power 50; U_BATTERY_S storage
  45000. Rooms, corridors, lights, doors, teleporters (-20), containers (-5),
  planters and the bio-dome (-50) also draw power.
- Power hotspot class strengths: REGIONHOTSPOTSTABLE (see
  [extraction-hotspots.md](extraction-hotspots.md)).
- Save, measured 2026-10-22 on Bob's save: a battery's charge is
  `UserData >> 32`; 13 of 50 batteries read exactly 45000 (full), the rest less.

## Scope and caveats

- Not in the save: the class of the power hotspot under each electromagnetic
  generator; biofuel fuel (every U_BIOGENERATOR has UserData 256, and no
  RefinerBuffer maintenance record lies within 4.9 m of one); which parts the
  wires join (saved wires stop 4-15 m short of generators).
- Rooms and lights draw only when wired, so a per-base sum of every powered part
  overstates demand. `nmsexporter/power.py` counts extractors as the demand and
  reports the rest as "up to".
- The battery unit is assumed to be kP x seconds (45000 = 15 min of one
  extractor); not measured against a game clock.
