---
type: DataLocation
title: Where the Harvest All radius lives, and how to change it
status: draft
evidence_level: game-data
builds: ["25800958"]
stale_after: next-build
sources:
  - research/sources/game-data/25800958/models/planets/biomes/common/buildings/parts/buildableparts/freighterbase/rooms/plantroom/parts/floor0/entities/interaction.entity.MXML.L59-175.xml
  - research/sources/game-data/25800958/models/planets/biomes/common/buildings/parts/buildableparts/bioroom/entities/interaction.entity.MXML.L160-280.xml
  - research/sources/web/2026-10-21-big-planter-harvest-all-mod.md
tags: [modding, farming, freighter]
related: [../mechanics/harvest-all-radius.md]
generated: {by: "machine:session", at: 2026-10-21}
verified: []
---

# Harvest All radius: file and field

| Room | Pak | File | Field |
|---|---|---|---|
| Freighter Hydroponic Room | `NMSARC.Precache.pak` | `models/planets/biomes/common/buildings/parts/buildableparts/freighterbase/rooms/plantroom/parts/floor0/entities/interaction.entity.mbin` | `GcTriggerActionComponentData` > state `HARVEST` > `GcHarvestPlantAction.Radius` (6.0) |
| Biodome | `NMSARC.Precache.pak` | `models/planets/biomes/common/buildings/parts/buildableparts/bioroom/entities/interaction.entity.mbin` | same, `Radius` 6.0 |

## Changing it

1. `scripts/nms-pak get 'plantroom/parts/floor0/entities/interaction'` unpacks
   and converts the file to MXML.
2. Edit `Radius`; convert back with `MBINCompiler-linux convert` (MXML -> MBIN).
3. Place the MBIN at the same path, upper-cased, under
   `GAMEDATA/MODS/<ModName>/` (loose-file mods).

Another mod that ships this file conflicts with yours. Rebuild after any game
update that changes the file (`scripts/nms-pak find` and compare).

## Related mod approach

"Big Planter - Harvest All" adds the action to the large planter instead,
editing `.../buildableparts/tech/cuberoom_plantermega.scene.mbin`
(community-claim, from the mod page).
