---
type: Measurement
title: Planet hazard tables vs the in-game hazard readout (one planet)
build: "25800958"
date: 2026-10-22
method: pymhf_mods/live_position.py 0.2 read cGcPlanet::mPlanetData (Weather, Hazard) for the nearest planet via cGcPlanet::UpdateWeather; Bob read the HUD hazard values at the same time, on foot near the Activated Indium base (system 382, planet 1). Sun angle from cGcSky mfSolarSunAngle.
---

# Readings

| Source | Temperature | Toxicity | Radiation |
|---|---|---|---|
| Planet Hazard table (6 slots) | 20, 10, 12, 140, 12, -158 | 0 x 6 | 0 x 6 |
| HUD, 21:39 local, sun angle 117.9649, PlanetOnFoot | 18.6 C | 8.9 | 0.9 |
| Bob, from earlier storms on this planet | storms reach about 140 | | |

Planet data at the same time: weather Humid, intensity Extreme, storm frequency
Low; resources Activated Indium, Paraffinium, Cobalt (matches the base built
there for Activated Indium, which supports the mPlanetData offset).

# Inferred

- Temperature slot 4 (index 3, 140) is the storm peak.
- The HUD's toxicity and radiation do not come from these tables (all zero).

# Not established

- Which slots are day, night and the others; whether the HUD temperature
  blends day (20) and night (10) by time of day (18.6 at sun angle 117.9649 would
  fit late day). A night reading would test it.
- Where the HUD toxicity and radiation come from.
- What SpookLevel (1, 6, 5, 16, 9, 0) measures.
