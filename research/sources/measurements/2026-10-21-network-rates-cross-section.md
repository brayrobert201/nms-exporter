---
type: Measurement
title: Measured extraction rate per pipe network vs extractors in it (cross-section of Bob's farms)
build: "25800958"
date: 2026-10-21
method: The exporter's per-network rate, measured from the change in depot+extractor fill between consecutive saves (rate_measured=True), read from /json farms at 2026-10-21 ~23:30. Extractor counts from the save's base objects grouped into pipe networks. One reading per network; each network is on a different hotspot.
---

# Readings (measured networks only)

| Network | Kind | Extractors | Measured items/h | Per extractor |
|---|---|---|---|---|
| Dioxite Radon - mineral | mineral | 2 | 1,015 | 507 |
| Copper Oxygen - mineral | mineral | 4 | 1,024 | 256 |
| Activated Indium | mineral | 5 | 935 | 187 |
| Magnetised Ferrite Nitrogen - mineral | mineral | 6 | 1,054 | 176 |
| Salt | mineral | 7 | 1,104 | 158 |
| Emiril | mineral | 7 | 1,042 | 149 |
| Gold | mineral | 9 | 1,418 | 158 |
| Silver | mineral | 10 | 1,337 | 134 |
| Cobalt Oxygen - mineral | mineral | 12 | 1,174 | 98 |
| Dioxite Radon - gas | gas | 5 | 869 | 174 |
| Magnetised Ferrite Nitrogen - gas 2 | gas | 6 | 1,573 | 262 |
| Magnetised Ferrite Nitrogen - gas | gas | 10 | 1,304 | 130 |
| Copper Oxygen - gas | gas | 11 | 1,170 | 106 |
| Cobalt Oxygen - gas | gas | 13 | 1,270 | 98 |

Earlier report from Bob (readings not retained): one standalone extractor at
300/h fell to 200/h once piped into a network.

# What it suggests, and why it is not yet evidence of a formula

Network totals sit between ~870 and ~1,570 items/h whether the network has 2
or 13 extractors, so adding extractors beyond a handful adds little. But:

- **Hotspot class and survey percentage are not recorded** (the save does not
  store them); a 2-extractor network at 1,015/h implies at least an A-class
  hotspot, so class differences alone could produce this spread.
- Distance of each extractor from the hotspot centre is not controlled.
- One reading per network, each from a single pair of saves.
- Networks with rate_measured=False show the exporter's assumption
  (extractors x 250/h x class C), which these readings say overestimates large
  networks: e.g. an 8-extractor network is assumed at 2,000/h.
