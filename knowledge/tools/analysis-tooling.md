---
type: Tool
title: Tools for analysing NMS mechanics
status: draft
evidence_level: community-claim
stale_after: 2027-04-21
sources:
  - research/sources/web/2026-10-21-pymhf-readme.md
  - research/sources/web/2026-10-21-nmspy-readme.md
  - research/sources/web/2026-10-21-mbincompiler-readme.md
  - research/sources/web/2026-10-21-hgpaktool-readme.md
  - research/sources/web/2026-10-21-libnom-io-readme.md
  - research/sources/web/2026-10-21-assistantnms-webapp-readme.md
  - research/runs/2026-10-21-tooling-survey/raw/survey.md
tags: [tooling]
generated: {by: "machine:session", at: 2026-10-21}
verified: []
---

# Analysis tooling

**Game data is covered by the toolchain already in use; hardcoded mechanics
(sale price drop, network falloff, wallet cap) need runtime hooking or
careful measurement, and nothing public documents them.**

## In this repo

| Tool | Use |
|---|---|
| `scripts/nms-pak` | Find any of the ~195k packed paths, unpack and convert, grep, and cite excerpts as sources. |
| `scripts/nms-data` | Query the extracted tables (items, recipes, crops, biomes). |
| `scripts/nms-extract-tables.py` | Rebuild `data/nms_tables.json` after a game update. |
| `scripts/research-fetch` | Store a web page verbatim with provenance. |
| `scripts/nms-decode-save.py`, `/json`, `/diff` | Save contents and save-to-save differences, the basis for measurements. |

## External

| Tool | What it gives the compendium | Caveat |
|---|---|---|
| HGPAKtool, MBINCompiler (monkeyman192) | Pak unpacking and MBIN<->MXML; already in `/opt/nmstools`. | One MBINCompiler release per game version. |
| pyMHF + NMS.py (monkeyman192) | Hook game functions at runtime and log inputs and outputs: the route to hardcoded formulas. NMS.py's function patterns and struct types are the nearest public reverse-engineering notes. | Windows-targeted; untested under Proton. Breaks on game updates until offsets are updated. |
| libNOM.io / NomNom (zencq) | Save read/write library and editor; libNOM.map is a maintained key de-obfuscation map; NomNom's source may encode field limits (wallet cap). | .NET; source not yet read. |
| NMSE, goatfungus NMSSaveEditor | Independent save decoders to cross-check field meaning. | |
| Assistant for NMS (AssistantNMS) | Recipe and price data extracted from game files - a cross-check, not new evidence. | Same source data as ours. |
| AMUMSS script collections | Show which fields modders treat as tunable. | Windows tooling. |

Not found (survey of 2026-10-21, limited search): per-version MXML dumps,
public Ghidra/IDA databases for NMS.exe, or any measured documentation of the
sale price drop, network falloff or wallet cap. The NMS Fandom wiki refused
automated fetches (HTTP 402).

## Next steps worth taking

- Commit a per-build MXML dump of the tables we read (or all of METADATA) to a
  separate repo so game updates diff with `git diff`.
- Try pyMHF/NMS.py under Proton for the sale and extraction functions.
- Read NomNom/libNOM source for the wallet cap.
