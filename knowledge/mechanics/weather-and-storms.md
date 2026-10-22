---
type: Mechanic
title: Weather and storms - storm timing, hazard table slots
status: draft
evidence_level: game-data
builds: ["25800958"]
stale_after: next-build
sources:
  - research/sources/game-data/25800958/gcskyglobals.globals.MXML.L68-92.xml
  - research/sources/game-data/25800958/metadata/simulation/solarsystem/weather/humidweather.MXML.L1276-1307.xml
  - research/sources/measurements/2026-10-22-planet-hazard-vs-hud.md
generated: {by: "machine:session", at: 2026-10-22}
verified: []
tags: [weather, hazards, live]
related: [base-power.md, save-coordinates.md]
verdict: >
  On a planet with Low storm frequency a storm lasts 120-180 s and the gap between
  storms is 900-2400 s; High: 150-320 s storms, 120-620 s gaps. A storm is
  announced 25 s ahead and takes 20 s to build and to clear.
---

# Weather and storms

**Storm length and the gap between storms depend on the planet's storm
frequency: Low = 120-180 s storms every 900-2400 s; High = 150-320 s storms
every 120-620 s. Warning 25 s, build-up and clearing 20 s each.**

## Evidence

- gcskyglobals: MinStormLengthLow/MaxStormLengthLow 120/180,
  MinStormLengthHigh/MaxStormLengthHigh 150/320, MinTimeBetweenStormsLow/High
  900/120, MaxTimeBetweenStormsLow/High 2400/620, ExtremeFallback 240-620,
  StormWarningTime 25, StormTransitionTime 20.
- Storm states (cGcSky::SetStormState): Inactive, Warning, TransitionIn,
  Active, TransitionOut.
- A planet's hazard tables (cGcPlanetHazardData: Temperature, Toxicity,
  Radiation, LifeSupportDrain, SpookLevel) are six values in the order Ambient,
  Water, Cave, Storm, Night, DeepWater; the weather file gives a Normal and an
  Extreme value for each (humid: ambient 12/20, storm 92/140, deep water
  -95/-158). The live mod read 20, 10, 12, 140, 12, -158 on an extreme humid
  planet, which is the Extreme column.

## Measured

One storm, 2026-10-22, Extreme humid planet with StormFrequency Low
(live_position weather log): warning 25.0 s, build-up 20.1 s, storm 315.0 s,
clearing 20.0 s. The storm length excludes the transitions, and 315 s fits the
High range (150-320), not Low (120-180): an Extreme planet appears to use the
High length.

The next storm went from Inactive to Active 359 s after the first cleared,
with no Warning or TransitionIn logged (the player was inside the corvette).
A gap of 314-359 s fits ExtremeFallback (240-620 s) and not Low (900-2400 s).

## Scope and caveats

- Two storms on one planet. An Extreme planet appears to use the High storm
  length and the ExtremeFallback gap whatever its StormFrequency.
- A storm can reach Active without Warning or TransitionIn being reported
  (seen once, from inside the corvette); why is not established.
- The HUD's current hazard readings are not these table values alone: 18.6 C
  ambient against a table value of 20, and 8.9 toxicity / 0.9 radiation where
  the tables are zero.
