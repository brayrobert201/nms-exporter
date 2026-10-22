---
type: Mechanic
title: Positions in the save - planet-centred bases, base-local objects
status: draft
evidence_level: measured
builds: ["25800958"]
stale_after: next-build
sources:
  - research/sources/measurements/2026-10-21-save-coordinate-frames.md
  - research/sources/measurements/2026-10-22-live-position-compass.md
tags: [save-format, mapping]
generated: {by: "machine:session", at: 2026-10-21}
verified: []
---

# Positions in the save

**A planetary base's `Position` is measured from the planet's centre; its
objects' positions are in the base's own frame (y up) and rotate onto the
planet with Up = base position, Forward = base Forward, Right = Up x Forward.**
Planet radii seen: about 64.6k, 98.4k and 130.1k units.

## Evidence

Bases sharing a GalacticAddress agree in |Position| to within ~70 units while
different planets cluster at three radii; the rotation is the one the
exporter uses to place refiners, which matches every planet-base refiner.

## Scope and caveats

Compass north is the planet's +Y axis and east = north x up, checked against
the in-game compass on 2026-10-22 (one planet), so latitude, longitude and
bearings derived from these frames are right, not mirrored. The live player
position (cGcPlayerEnvironment mPlayerTM.pos minus mNearestPlanetPos) is in
the same planet-centred frame; mPlayerTM.at points behind the player.
cGcPlayerEnvironment's distance-from-planet is |position| minus a round nominal
radius (130048 = 127 x 1024, 98304 = 96 x 1024), and its sea-level field is the
water surface above that radius: 120 on a water planet, 0 on every dry planet
seen (measured 2026-10-22 with the live_position mod). Freighter
and corvette bases use another frame.

## Open

Frames of markers, surveyed events, drained deposits and exocraft positions.
