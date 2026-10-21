---
type: Mechanic
title: Positions in the save - planet-centred bases, base-local objects
status: draft
evidence_level: measured
builds: ["25800958"]
stale_after: next-build
sources:
  - research/sources/measurements/2026-10-21-save-coordinate-frames.md
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

Which axis is north, and east/west handedness, are not yet checked against the
in-game compass; until then latitude, longitude and compass bearings derived
from these are unverified. Freighter and corvette bases use another frame.

## Open

Frames of markers, surveyed events, drained deposits and exocraft positions.
