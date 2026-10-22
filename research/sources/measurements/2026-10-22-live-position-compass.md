---
type: Measurement
title: Live player position vs save frame, and compass north/east
build: "25800958"
date: 2026-10-22
method: pymhf_mods/live_position.py hooked cGcPlayerEnvironment::Update and wrote mPlayerTM, mNearestPlanetPos and mUp once a second. Bob stood in the Cobalt Oxygen base, then faced due north and due east on the in-game compass for a few seconds each; the samples at those times were compared with the save's base Position and with nmsexporter/maps.py's tangent_frame.
---

# Readings

| What | Value |
|---|---|
| Live rel = mPlayerTM.pos - mNearestPlanetPos (IndoorInBase) | (-103273.0, -2775.1, -79488.1), \|rel\| 130,351 |
| Save Position of Cobalt Oxygen base | (-103276.4, -2752.9, -79481.4), \|P\| 130,349 |
| Distance between them | 21.6 |
| mUp vs normalised rel | (-0.792, -0.021, -0.610) both |
| Walking steps (> 3 m) where movement was opposite mPlayerTM.at | 15 of 18 (cos -0.96 to -1.00) |
| Facing north: -at, made tangent | (0.005, 0.999, -0.042) |
| Facing east: bearing by maps.py (north = +Y tangent, east = north x up) | 89.4 deg |

# Inferred

- Player position minus nearest planet centre is the same planet-centred frame
  as PersistentPlayerBases.Position.
- mPlayerTM.at points behind the player; facing is -at.
- Compass north is the planet's +Y axis and east = north x up, as maps.py
  assumed: bearings and latitude/longitude from the save are correct, not
  mirrored. Longitude atan2(x, z) increases eastward.

# Not established

- The 3 walking steps with movement along +at (one 27 m step on landing) were
  not examined; likely backing up or the ship-to-foot transition.
- Tested on one planet (radius ~130.3k) only.
