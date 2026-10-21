---
type: Question
title: "How does extractor yield fall with distance from the hotspot centre?"
status: partial
asked: 2026-10-21
decides: "Where to place extractors relative to the survey marker."
tags: [farming, extraction]
runs: []
answered_by: []
---

# How does extractor yield fall with distance from the hotspot centre?

## Why it matters

Where to place extractors relative to the survey marker.

## Known so far

Current belief: full within 100u, zero at 500u, survey marker up to 150u off the centre. The exporter reads a falloff from the globals; which fields, and whether the curve is linear, should be cited.

## What would answer it

A game-data citation (`scripts/nms-pak`) for the values, plus a measurement or code evidence for the behaviour.

## Measurement plan

On one hotspot (class and survey % noted), place single unpiped extractors,
each with its own depot and power, in a straight line from the survey marker:
about 0, 100, 200, 300, 400 and 500u out. At each spot screenshot the survey
percentage before building. Save, wait 2 h, save. Exact distances between
extractors come from the save's object positions; the rate per extractor from
the fill change. This gives yield against distance and against the displayed
survey percentage, and checks the 100u / 500u falloff fields. Trigger a save at each step (enter your ship, or use a save point; the exporter picks up the new save within seconds). Read results with `curl -s 'localhost:9877/diff?against=1'` or `scripts/nms-rundown.py --diff`, and give the readings to a session to store under `research/sources/measurements/`.
