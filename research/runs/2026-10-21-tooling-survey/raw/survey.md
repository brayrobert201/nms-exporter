<!--
  what: return of one searcher (machine:searcher) asked to survey tooling for analysing NMS mechanics
  date: 2026-10-21
  method: WebFetch of GitHub, PyPI and GitHub REST API pages plus web search; nothing installed
  note: abridged by the orchestrating session - tables condensed, every claim and caveat kept.
        The READMEs it relied on are stored under research/sources/web/2026-10-21-*-readme.md.
  review: none yet (not a full run; no adversarial review)
-->

# Tooling survey (searcher return, abridged)

## Caveats reported by the searcher
- NMS Fandom wiki: HTTP 402 on every fetch including api.php; API, licence and content unverified.
- No tool or repo found that documents the per-sale price drop, extraction network falloff,
  Harvest All behaviour or the units cap. No public Ghidra/IDA database or headers for NMS.exe.
  Limited search; not proof of absence.

## Data extraction
- HGPAKtool (monkeyman192, MIT): release 1.1.3 2026-02-16, pushed 2026-09-23; Linux binaries; paks from 5.50 on.
- MBINCompiler (monkeyman192): v7.07.0-pre1 2026-10-08; Linux build; one release per game version; licence file not read.
- libMBIN: URL tried 404; location unverified.
- NMSModBuilder (cmkushnir, AGPL-3.0): pushed 2026-10-08; low relevance.
- AMUMSS (HolterPhylo, MIT): pushed 2025-12-13; Windows-oriented. Script collection
  MetaIdea/nms-amumss-lua-mod-script-collection pushed 2026-10-07 shows which fields modders tune.
- No per-version MXML dump repo or NMS-specific diff tool found.
- zencq/Pi (procedural item collection, no licence listed), NMSCD RewardTableTools (GPL-3.0, pushed 2026-10-19).

## Runtime / code analysis
- pyMHF (monkeyman192, MIT): Python function hooking by offset; 0.2.5; PyPI classifier Win32 only; Proton unverified.
- NMS.py / NMSpy (monkeyman192, MIT): function and struct definitions on pyMHF; README warns updates break it;
  tools/data.json and nmspy/data/types.py hold patterns and layouts (not read).
- No public Ghidra/IDA projects found.

## Save analysis
- NomNom (zencq, GPL-3.0, pushed 2026-10-21); libNOM.io (GPL-3.0, 0.14.2 2025-09-06; libNOM.map key mapping).
- goatfungus NMSSaveEditor (Java, pushed 2026-06-05, licence not stated); NMSE (vectorcmdr, AGPL-3.0, pushed 2026-10-02);
  nmssavetool (MIT, 2022, old); NMSCD nms-save-web-editor (GPL-3.0).

## Community sources
- Assistant for NMS: data extracted from game files with MBINCompiler; no public API docs found; GPL-3.0 (WebApp).
- NMSCD: ~49 small utility repos; none a mechanics database.
- STEP modding wiki: data-structure background only.

## Measured mechanics
- Price drop per sale: only anecdotes (Steam threads; totals of up to ~-80% after heavy selling); no per-sale
  rate or recovery rate found. Nothing found for network falloff, crop growth modifiers, Harvest All or the wallet cap.

## Searcher's ranking
1. pyMHF + NMS.py  2. MBINCompiler + HGPAKtool with a per-version MXML git repo  3. NomNom/libNOM source
4. NMS.py data files as RE notes  5. NMSE / goatfungus as independent decoders.
