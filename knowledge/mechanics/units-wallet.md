---
type: Mechanic
title: Units are a 32-bit value; saves write them signed
status: draft
evidence_level: measured
builds: ["25800958"]
stale_after: next-build
sources:
  - research/sources/measurements/2026-10-21-device-sale-and-wallet.md
tags: [economy, save-format]
related: [../../research/questions/units-wallet-cap.md]
generated: {by: "machine:session", at: 2026-10-21}
verified: []
---

# Units wallet encoding

**The save's `Units` field is a 32-bit value written as a signed integer: past
2,147,483,647 it reads negative, and adding 2^32 gives the real balance.** The
exporter corrects for this since commit 124cf31 (units, nanites, quicksilver).

## Evidence

A balance of 788,126,648 plus a sale of 89 devices was written as
-2,116,588,792, which is 2,178,378,504 unsigned and matches the proceeds to
within the price band (15.62M per device against a 15.6M base).

## Scope and caveats

Observed for Units only. The cap (presumably 4,294,967,295) and what the game
does on reaching it are not observed.
