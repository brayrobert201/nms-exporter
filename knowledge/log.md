# Log

Newest first. One entry per change to the bundle: what landed, from where.

## 2026-10-22 - base power, heights

- New concept: base power (part ratings, battery charge = UserData >> 32, what the
  save omits); `/map` shows a power verdict per base. Ground heights from live
  samples: distance_from_planet is height above a round nominal radius.

## 2026-10-22 - compass north and live position

- Measured with the live_position mod: compass north = planet +Y, east = north
  x up (maps.py was right); live player position is in the save's
  planet-centred frame (21.6 from the base Position). `/map` drops its
  "north assumed" notes. Source:
  `research/sources/measurements/2026-10-22-live-position-compass.md`.

## 2026-10-22 - first live pyMHF attach

- `scripts/nms-hook` attached to the running game (2 mods, 5 hooks). A second
  attach into the same game run failed and pyMHF closed the game; Ctrl+C takes
  the same exit path. Launcher now refuses a second attach and has `--detach`.
  Notes: `research/runs/2026-10-21-pymhf-proton/raw/notes.md` (Live test).

## 2026-10-21 - pyMHF under Proton, map, farm check

- pyMHF + NMS.py install and import inside the game's Proton prefix; version
  matches the installed NMS.exe; launcher `scripts/nms-hook` (attach only).
  Notes: `research/runs/2026-10-21-pymhf-proton/raw/notes.md`.
- New concept: coordinate frames of save positions; `/map` page and
  `scripts/nms-farm-check` use it.

## 2026-10-21 - measurement plans

- Measurement plans added to six questions (sale price drop, Gold yield,
  network falloff, hotspot distance, wallet cap, refiner speed, crop growth).
- New measurement: network rate vs extractor count across Bob's 14 measured
  networks (`research/sources/measurements/2026-10-21-network-rates-cross-section.md`);
  extraction-network-falloff moved to partial.

## 2026-10-21 - bundle created

- Scaffolded: `research/` charter, question register, sources store; `knowledge/`
  conventions; tools `scripts/nms-pak`, `scripts/research-fetch`,
  `scripts/okf-lint`, `scripts/research-index`.
- Seeded concepts (machine:session, unreviewed): Harvest All radius (mechanic
  and data location), extraction hotspots, units wallet encoding, analysis
  tooling.
- Seeded 10 questions from play: sale price drop, Gold sale yield, network
  falloff, hotspot yield distance, hotspot minerals (partly answered: Ammonia
  is in the extractable list), Harvest All behaviour, wallet cap, system price
  band, crop growth modifiers, refiner size and speed.
- Tooling survey stored as a searcher return in
  `research/runs/2026-10-21-tooling-survey/raw/survey.md`.
