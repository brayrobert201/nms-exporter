---
type: Mechanic
title: Mission stage gating - what a stage waits for, and which item conditions are only branch guards
status: draft
evidence_level: game-data
builds: ["26438455"]
stale_after: next-build
sources:
  - data/nms_tables.json#missions
generated: {by: "machine:session", at: 2026-11-06}
verified: []
tags: [missions, save-format]
related: []
verdict: >
  An item condition on a mission only means "you need this" when a stage
  waits for it. A WaitForConditions stage waits until its ConditionTest
  holds over its own Conditions. A Group's Conditions are its exit test:
  the group runs its stages until the test holds, and is skipped if it
  already holds. So most HasProduct / HasSubstance conditions on groups are
  branch guards ("does not have treat" exits once you have it). Conditions
  themselves have no polarity; only ConditionTest (AllTrue / AnyTrue /
  AllFalse / AnyFalse) does.
---

# Mission stage gating

**A stage needs an item when it is a Collect / Craft / Build / Construct /
RepairTech stage, or a WaitForConditions stage whose own ConditionTest is
positive over item conditions. Item conditions on groups are exit tests.
They give a need only for a Stop stage (which blocks until its group exits)
and for the objective groups the log shows.**

## Evidence

From the mission tables (`metadata/simulation/missions/tables/*.MXML`),
read through `scripts/nms-extract-tables.py`:

- `ACT1_STEP2`: a group "bail if the scan event vanishes" has
  `IsScanEventActive` under `ConditionTest=AnyFalse`. The main wrapper has
  `MissionMessage A1S2_DONE` under `AnyTrue` with `RepeatLogic=Loop`, so a
  group's test is the condition for leaving it. Progress 8 and 9 are
  CollectSubstance stages for 10 STELLAR2 and 10 CATALYST1.
- `PB_TUT`: the sibling groups "does not have treat" (`HasProduct
  TREAT_FREELEVEL`, `AnyTrue`) and "has treat" (the same condition,
  `AnyFalse`) pick a branch. Neither one tells the player to collect
  anything. Progress 18 is a WaitForConditions on `HasProduct CHART_PB_CHALL`
  with `AnyTrue` (get it). Progress 19 is the same condition under `AnyFalse`,
  "use the invitation": the stage waits until the item is gone.
- `PIRATES1` progress 11, "deploy the beacon": a WaitForConditions on
  `HasProduct PIRATE_BEACON 1` under `AnyFalse`, so it is a "use" need.
- `BONES_TUT` progress 3 is a WaitForScanEvent. Its group has an
  ObjectiveID ("learn a plinth recipe") and five `ProductKnown FOS_*`
  conditions under `AnyTrue`, so the player needs to know any one of them.
- `PB_TUT` progress 11 is a WaitForConditions with no conditions under
  `AnyFalse`, which can never hold. Like Stop (`PB_TUT` 14, "quit the gene
  editor"), it holds the stage until its group's exit test holds.

## What the extractor emits

`missions.<id>.needs` = `[progress, [{id, item, amount, kind, type, any?}]]`
and `missions.<id>.events` = `[progress, scan event]`. The `units` entry in
the JSON describes both. These are left out:

- conditions under silent groups, which are branch guards;
- an AnyTrue test that mixes item and non-item conditions, where the item is
  only one way out;
- procedural or season-driven items (`Default`, `UseDefaultValue`,
  `Take*FromSeasonData`, CollectLocalSubstance, HasProcProduct);
- Construct stages that pick N of a larger part list at random;
- nested condition groups.

An objective group's exit test is added only to blocking stages that ask for
no item themselves, and only from the innermost such group.

## Scope and caveats

The semantics come from reading the structure and debug strings across all
27 tables, not from the game code. Where a stage's condition is an any-of
that includes "already have the end product" (`ACT2_STEP4`: "1 Soul Engine
or 120 Cadmium"), the any-of is kept as written. `ATLAS11` lists the seed
chain the same way. Events come from a stage's own Event field, from scan
events tested by its own conditions, and from IsScanEventLocal on enclosing
groups. Group-level "is the event still active" tests are left out.

## Open

- Whether a group's exit test is checked every frame or only at stage
  boundaries. The "bail if the scan event vanishes" groups suggest every
  frame.
