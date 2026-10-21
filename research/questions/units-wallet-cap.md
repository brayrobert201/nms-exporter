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

## Measurement plan

**Be careful: if the game wraps rather than clamps, crossing the cap could
take you from ~4.29B to near zero.** You are at ~2.18B; one full device run
adds ~1.4-1.7B, so the run after next would reach the cap.

1. Before you get within ~200M of 4,294,967,295, **back up the save folder**
   (`~/.local/share/Steam/steamapps/compatdata/275850/pfx/drive_c/users/steamuser/AppData/Roaming/HelloGames/NMS/st_*`)
   with the game closed.
2. Sell single cheap items until you are within one device (15.6M) of the cap,
   saving and noting the in-game balance.
3. Sell one device, save, and screenshot the balance and any message.
4. If the balance wrapped or vanished, close the game without saving again and
   restore the backup.

Until this is known, the safe rule is to stop selling at ~4.2B and hold the
rest as devices. Trigger a save at each step (enter your ship, or use a save point; the exporter picks up the new save within seconds). Read results with `curl -s 'localhost:9877/diff?against=1'` or `scripts/nms-rundown.py --diff`, and give the readings to a session to store under `research/sources/measurements/`.
