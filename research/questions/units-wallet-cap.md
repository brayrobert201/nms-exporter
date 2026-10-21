---
type: Question
title: "What happens when units reach the 32-bit cap?"
status: open
asked: 2026-10-21
decides: "When to stop selling into units and hold value as devices or other items instead."
tags: [economy]
runs: []
answered_by: [../../knowledge/mechanics/units-wallet.md]
---

# What happens when units reach the 32-bit cap?

## Why it matters

When to stop selling into units and hold value as devices or other items instead.

## Known so far

Units are stored as a 32-bit value (the save writes them signed; 2,178,378,504 read as -2,116,588,792). Unsigned max is 4,294,967,295. Unknown whether sales are refused, clamped or overflow at the cap.

## What would answer it

Likely hardcoded: a runtime hook (pyMHF) or disassembly, or a careful measurement series stored under `research/sources/measurements/`.
