---
type: Measurement
title: Device sale proceeds and the wallet's signed read-out
build: "25800958"
date: 2026-10-21
method: Two consecutive saves read by the exporter (/json and the save's PlayerStateData.Units), before and after Bob sold devices at a trade terminal; item counts from the same saves.
---

# Readings

| | Before sale (save3.hg, 22:43) | After sale (save4.hg, 22:44) |
|---|---|---|
| `Units` as written in the save | 788,126,648 | -2,116,588,792 |
| Same value read as unsigned 32-bit | 788,126,648 | 2,178,378,504 |
| Fusion Ignitor (ULTRAPROD1) held | 29 | 2 |
| Stasis Device (ULTRAPROD2) held | 64 | 2 |

Derived:
- Sold 27 Fusion Ignitors + 62 Stasis Devices = 89 units of products with a
  base value of 15,600,000 each (product table).
- Proceeds 2,178,378,504 - 788,126,648 = 1,390,251,856, i.e. 15,620,807 per
  device on average, 0.13% above base.
- -2,116,588,792 + 2^32 = 2,178,378,504, consistent with the proceeds, so the
  save stores Units as a 32-bit value that the JSON writes signed.

# Not recorded

- The system, its economy type and the price shown at the terminal.
- Whether the 89 were sold in one transaction or several, and in what order.
- Nanites and quicksilver did not cross 2^31, so their encoding is inferred
  from Units only.
