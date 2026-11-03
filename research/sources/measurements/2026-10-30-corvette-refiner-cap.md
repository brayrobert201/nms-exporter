---
type: Measurement
title: Refiner output caps - the corvette's 4,096 and Paraffinium's 4,095
build: "26308211"
date: 2026-10-30
method: Decoded save3.hg and save4.hg (scripts/nms-decode-save.py) and read every RefinerBufferKeys entry with Location 8 (the corvette) alongside the freighter's (Location 2); compared slot Amount and MaxAmount with the recipe loaded.
---

# Readings

| Where | Recipe | Slots (id, amount, MaxAmount) | Last update / completed |
|---|---|---|---|
| Corvette, B_WALL_TECH0 at (-3, 3, 6) | Recycle Waste Materials, 1 Rusted Metal -> 2 Ferrite Dust | SPACEGUNK3 2048 / 9999 (input); LAND1 4096 / 9999 (output) | both 2026-10-30 22:00, unchanged in the next save an hour later |
| Freighter Big Bob, refiner room | Gas Transfer, Nitrogen + Oxygen -> Sulphurine | GAS3 9699, WATER1 9969, FUEL2 712, all MaxAmount 9999 | running |
| Freighter Big Bob, refiner room | several | inputs up to 9,969 in one slot | running |

- The save's DifficultyState.Settings.InventoryStackLimits is High; the
  difficulty table gives the MaintenanceObject group 9999 per substance slot
  at that setting, which the freighter's 9,969-unit input confirms.
- The corvette refiner stopped with its output at exactly 4,096 and exactly
  half that of input left: 2,048 operations of a 1 -> 2 recipe from an empty
  output, with 4,096 of input loaded.
- In game on the freighter, a Paraffinium output (Mineral Alchemy, 1 + 1 ->
  2) will not go past 4,095 (player observation, same day).
- MaxAmount in the save reads 9999 on the corvette's slots too, so it is not
  the operative cap there.

# Inferred

- A substance output stops at 4,095 in every refiner, and the game takes one
  more operation whenever the output is below that (4,094 -> 4,096 on the
  corvette's 1 -> 2). Input slots hold the MaintenanceObject cap for the
  setting (9,999 on High); the corvette's 4,096 of input loaded is taken as
  that slot's size until a save shows more.

# Not established

- Where the 4,095 comes from: neither the refiner entities
  (models/common/spacecraft/biggs/entities/refiner.entity and the freighter
  and base ones), the difficulty table nor the globals carry it. Whether the
  corvette's input slot is really 4,096, and whether the output stop moves
  with the stack-limits setting, needs one more reading each.
