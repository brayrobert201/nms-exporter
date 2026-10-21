---
type: Question
title: "Do small, medium and large refiners differ in speed, and does the freighter refiner?"
status: open
asked: 2026-10-21
decides: "Which refiners to run the Gold and Herox recipes in."
tags: [refining]
runs: []
answered_by: []
---

# Do small, medium and large refiners differ in speed, and does the freighter refiner?

## Why it matters

Which refiners to run the Gold and Herox recipes in.

## Known so far

Recipe time is TimeToMake / RefinerSubsMadeInTime (250) for substances, / 2 for products. Whether refiner size or location changes it is not established.

## What would answer it

A game-data citation (`scripts/nms-pak`) for the values, plus a measurement or code evidence for the behaviour.

## Measurement plan

Run the same recipe (Gold, Chromatic Alchemy, with full input stacks) at the
same time in a portable refiner, a medium refiner, a large refiner and a
freighter refiner. Save at the start, again after 10 minutes, and again after
30. The exporter reports each refiner's output from the save; output per
minute per refiner answers it. Trigger a save at each step (enter your ship, or use a save point; the exporter picks up the new save within seconds). Read results with `curl -s 'localhost:9877/diff?against=1'` or `scripts/nms-rundown.py --diff`, and give the readings to a session to store under `research/sources/measurements/`.
