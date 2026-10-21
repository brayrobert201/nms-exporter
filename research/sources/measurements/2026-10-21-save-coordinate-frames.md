---
type: Measurement
title: Coordinate frames of positions in the save
build: "25800958"
date: 2026-10-21
method: Decoded the newest save (scripts/nms-decode-save.py), grouped PersistentPlayerBases by GalacticAddress and took |Position|; inspected base object Up vectors and power-line geometry at the Cobalt Oxygen base; the planet-base rotation is the one the exporter uses to match refiner maintenance keys (nmsexporter/nms.py _planet_base_refiners), which places every planet-base refiner correctly.
---

# Readings

| Planet (GalacticAddress) | Bases on it | |Position| of each base |
|---|---|---|
| 4637740068801594 | Copper Oxygen, Oxygen Extractor, Lisaga-Skop Outpost, Gold | 130,089 / 130,122 / 130,087 / 130,096 |
| 0x206F00049A8D1F | Icy resource rich, Salvage Data 1, Dioxite Radon | 64,667 / 64,701 / 64,636 |
| 0x208E00FC6D1115 | Salt, Emiril | 130,081 / 130,084 |
| (others, one base each) | | 98,439; 64,616; 64,791; 64,857; 130,230; 98,383; 98,407; 130,349 |

- Bases on one planet agree to within ~70 units; across planets the values
  cluster at ~64.6k, ~98.4k and ~130.1k.
- Base objects carry Up ~ (0.02, 0.999, 0.03): their positions are in the
  base's own frame with y up.
- Freighter and corvette bases have small |Position| (1,642; ~13.5k): a
  different frame.

# Inferred

- PersistentPlayerBases.Position is planet-centred; the spread on one planet
  is terrain height. Planet radii seen: ~64.6k, ~98.4k, ~130.1k units.
- Base-local (x, y, z) maps to planet axes as x -> Right, y -> Up, z ->
  Forward, with Up = normalised base Position, Forward = base Forward made
  orthogonal to Up, Right = Up x Forward (exporter, verified on refiners).

# Not established

- Which planet axis is the pole the in-game compass points to (+Y assumed),
  and the handedness of east/west. One in-game compass reading from a base
  computer towards a known object would settle both.
- The frames of MarkerStack.BuildingLocation, SurveyedEventPositions,
  DrainedTerrainResourceDeposits and VehicleOwnership positions (magnitudes
  look planet-centred too; not checked object by object).
