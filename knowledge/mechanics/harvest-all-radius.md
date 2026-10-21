---
type: Mechanic
title: Harvest All Plants radius
status: draft
evidence_level: game-data
builds: ["25800958"]
stale_after: next-build
sources:
  - research/sources/game-data/25800958/models/planets/biomes/common/buildings/parts/buildableparts/freighterbase/rooms/plantroom/parts/floor0/entities/interaction.entity.MXML.L59-175.xml
  - research/sources/game-data/25800958/models/planets/biomes/common/buildings/parts/buildableparts/bioroom/entities/interaction.entity.MXML.L160-280.xml
  - research/sources/web/2026-10-21-harvest-all-freighter-mod.md
tags: [farming, freighter, biodome]
related: [../data-locations/harvest-all-radius.md, ../../research/questions/harvest-all-behaviour.md]
generated: {by: "machine:session", at: 2026-10-21}
verified: []
---

# Harvest All Plants radius

**Harvest All has a radius of 6.0 (game units, taken to be metres) in both the
freighter Hydroponic Room and the Biodome.** It is a setting of the room you
interact with, not of the crops.

## Evidence

- Freighter Hydroponic Room floor entity: a `GcSimpleInteractionComponentData`
  named `UI_HARVEST_ALL` ("Harvest All Plants") with `TriggerAction` `HARVEST`;
  the `HARVEST` state runs `GcHarvestPlantAction` with `Radius` `6.000000`.
- Biodome interaction entity: the same action and the same `Radius` 6.0.
- The crop's own interaction entity (e.g. Gamma Weed, `farmradioactive`) has no
  harvest radius; its only distances are `ScanRange` 550 and
  `DeactivateSimilarInteractionsNearbyRadius` 0.
- A published mod ("Harvest All Plants From Freighter") says it raises the
  freighter's Harvest All radius to cover the whole freighter, which agrees
  with the radius being a data value (community-claim; the mod's files were
  not inspected).

## Scope and caveats

Build 25800958 (Cosmos 7.06). The value is game-data; how the game applies it
(centre point, sphere or cylinder, whether it crosses rooms or floors) is not
observed. Six metres is roughly one room, which matches play: Harvest All has
to be triggered in each hydroponic room.

## Open

[What the radius measures and what raising it costs](../../research/questions/harvest-all-behaviour.md).
