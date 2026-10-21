---
type: Question
title: "Does anything change crop growth time or yield?"
status: open
asked: 2026-10-21
decides: "Whether to move crops between the freighter, Biodomes and planet bases."
tags: [farming]
runs: []
answered_by: []
---

# Does anything change crop growth time or yield?

## Why it matters

Whether to move crops between the freighter, Biodomes and planet bases.

## Known so far

Crop yields and grow times come from the reward tables (e.g. Star Bramble 25/4h, Fungal Cluster 50/4h). Unknown whether location, Biodome, freighter or any upgrade modifies them.

## What would answer it

A game-data citation (`scripts/nms-pak`) for the values, plus a measurement or code evidence for the behaviour.

## Measurement plan

Plant the same crop (Frostwort: 1 h, 50 per harvest) at the same time in a
freighter hydroponic room, a Biodome and an ordinary planter on a planet base.
Save straight after planting. Check each at 55, 60 and 65 minutes and note
which are ready, saving each time; harvest one plant from each and note the
amount. The save records planting times, so the exporter can compare actual
readiness against the table's 1 h. Trigger a save at each step (enter your ship, or use a save point; the exporter picks up the new save within seconds). Read results with `curl -s 'localhost:9877/diff?against=1'` or `scripts/nms-rundown.py --diff`, and give the readings to a session to store under `research/sources/measurements/`.
