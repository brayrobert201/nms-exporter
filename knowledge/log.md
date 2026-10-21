# Log

Newest first. One entry per change to the bundle: what landed, from where.

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
