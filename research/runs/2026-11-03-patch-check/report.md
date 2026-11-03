---
type: RunReport
title: Patch check 2026-11-03 - Forsaken (7.10 to 7.13) against the exporter
date: 2026-11-03
installed_build: "26331461"
by: machine:session (read-only scout; nothing tracked was modified, nothing deployed)
---

# Patch check, 2026-11-03

Raw material is under `raw/`: the official patch-note texts (`raw/web/`), the Steam
build history, MBINCompiler logs, the diff outputs and the scripts that made them
(`raw/scripts/`, all standard library, run with `python3 -I`).

## 1. What is installed, and which patch

| Fact | Value | Evidence |
|---|---|---|
| Steam build installed | **26331461**, depot 275851 manifest 3089640147238314487, installed 2026-10-30 18:47 UTC | appmanifest_275850.acf; Steam content_log |
| NMS.exe | 89,535,560 bytes, sha256 `a77fc298...4c6109`, PE FileVersion/ProductVersion **184271** (was 181442 on build 25800958) | `strings -el NMS.exe` |
| Public Steam branch now | buildid 26386568, updated 2026-11-02 18:15 UTC, **but the Windows depot's public manifest is the one installed** (3089640147238314487); only the macOS depot differs | api.steamcmd.net (`raw/web/api.steamcmd.net-275850.json`) |

So the PC files on disk are the current public PC content; nothing is waiting to download.

Builds since the tables were extracted (Steam content_log, install times, UTC):

| Build | Installed (UTC) | Patch (best match) |
|---|---|---|
| 25800958 | 2026-10-08 10:32 | Cosmos 7.06/7.07 era; data/nms_tables.json meta |
| 26271326 | 2026-10-28 13:26 | **Forsaken 7.10** (released 2026-10-28; MBINCompiler's "Update for NMS steam build id 26271400" was committed the same day) |
| 26277414 | 2026-10-28 17:32 | same-day 7.10 hotfix, no notes found |
| 26308211 | 2026-10-29 21:22 | 7.11 (PC, notes dated Oct 29) - inferred from the dates |
| 26331461 | 2026-10-30 18:47 | **installed**. NMS.py's 184271.0 (2026-10-31) targets this exe. Official notes for **7.13** ("now live on Steam") are dated 2026-11-02, and the public buildid moved on Nov 2 without changing the Windows depot. Either 7.13's PC files went out in 26331461 and the notes came later, or 26331461 is an unannounced PC 7.12 and 7.13 has not changed the PC files. **Not resolved.** The exe carries no "7.1x" string, so the version number cannot be read from it. |

Patch notes (official = level 4, Hello Games):
- 7.10 Forsaken: https://www.nomanssky.com/forsaken-update/ (stored: `raw/web/nomanssky.com-forsaken-update-7.10.txt`); Steam announcement https://store.steampowered.com/news/app/275850/view/679639664218341696
- 7.11 (Oct 29, PC + consoles): https://www.nomanssky.com/2026/10/forsaken-7-11/ - one crash fix (warping)
- 7.12 (Oct 30, PS5): https://www.nomanssky.com/2026/10/forsaken-7-12/ - one crash fix (Anomaly teleporter)
- 7.13 (Nov 2, "live on Steam"): https://www.nomanssky.com/2026/11/forsaken-7-13/
- Release log: https://www.nomanssky.com/release-log/
- The Fandom wiki pages (Update_7.10, Patch_notes) returned HTTP 402 to the fetcher and were not used. A web search summary said the wiki lists 7.11 for Oct 29-30 and 7.12 for PS on Oct 30; that agrees with the official pages.

What the notes say about the areas the exporter covers. "Notes" means official notes; "data" means today's table decode (section 3).

| Area | Notes say | Data says |
|---|---|---|
| Refiner / cooking recipes | nothing | **all 1,684 recipes identical**: ids, ingredients, amounts, results, TimeToMake (clean decode) |
| Item values, stack sizes | nothing on values. 7.10: "fixed rare issues with transferring stacks between inventories (stack partially lost or duplicated)" | 0 BaseValue changes on the 5,235 existing items. Substance StackMultipliers unchanged. difficultyconfig stack limits unchanged (suspect decode for items, clean for difficultyconfig) |
| Extraction / hotspots | nothing | hotspot classes, strengths, ranges, biome gases and substances unchanged; falloff and survey distance unchanged (clean decode, except the gameplay globals) |
| Crops / growth | nothing | **not checkable**: the base-building table does not decode (see 2) |
| Base parts / power | 7.10: **the Oxygen Harvester can now be built anywhere on a planet's surface, not only inside a base**. Corvette landing pad at planetary trading outposts | new Gravitational Flooring/Ramp/Wall (GRAV_*, 25 LAND3 each). Base-part power ratings not checkable |
| Frigates / fleet | nothing (freighter-battle spawn fixes only) | fleet globals and frigate traits unchanged (clean decode) |
| Missions | 7.10: Space Courier (package) missions from deep-space outposts; a Holo-Arena challenger at outposts; better mission names and guidance. 7.13: a Corvette Haulage variant that delivers to space stations; a Forsaken trader tutorial fix | **not checkable**: none of the 27 mission tables decode |
| Save format | nothing | 33 new obfuscated keys in the 7.10 mapping, none removed or renamed. 21 of them occur in the current save, all under `CommonStateData/SeasonData/SeasonalUAStationTradeData` (barter UI text). Save `Version` reads 4745 (no pre-patch value on file to compare) |
| Corvette | 7.10: new biomechanical modules, cockpits, a hab and interior set, traded from Forsaken traders for "mementos"; snapping fixes. 7.13: parts that block the player can be deleted in edit mode; visual fixes and optimisations | 220 new corvette BuildingParts (below). Corvette parts B_GEN_4, B_GEN_5 and B_TUR_F renamed |
| Freighter | freighter-battle spawn fixes; 7.13: can enter the freighter after a battle again | nothing in the tables |
| Difficulty / stack-limit settings | nothing | difficultyconfig `InventoryStackLimitsOptionData`: byte-identical to the 26308211 excerpt (clean decode) |
| Trading / economy | 7.10: Forsaken traders barter mementos for corvette parts, a Larva Cannon Multi-Tool for preserved grubs, and a Larva Tank helmet; no price or economy changes noted. 7.13: fixed losing mementos when buying a part with a full inventory | 6 memento items (SPOOK_PACKAGE1-6, 140,000 u each); new barter keys in the save |

Other notes (seamless warping, minimal HUD, multi-tool wheel, iOS) do not touch the exporter.

## 2. Toolchain

- `/opt/nmstools/MBINCompiler-linux` reports **v7.04.1-pre3** (libMBIN 7.4.1.3, released 2026-09-24 for build 25511792).
- Newer releases on GitHub (monkeyman192/MBINCompiler):
  - v7.07.0-pre1 (2026-10-08, for 25800958).
  - **v7.10.0-pre1 (2026-10-28 20:56 UTC), "Update for NMS steam build id 26271400"**, which is 7.10. Its report.json shows 463/469 templates passing, including NMS_REALITY_GCRECIPETABLE, GCSUBSTANCETABLE, GCPRODUCTTABLE, PROCEDURALPRODUCTTABLE, BASEBUILDINGOBJECTSTABLE, every *MISSIONTABLE, REWARDTABLE, FRIGATETRAITTABLE, REGIONHOTSPOTSTABLE, DIFFICULTYCONFIG and GCGAMEPLAYGLOBALS. Its failures are GCSCENEOPTIONS, DEFAULTSAVEDATA, three .ANIMs and LAUNCHTUBEDATA.ENTITY.
  - There is no release after 7.10.0-pre1. Whether it also reads 26331461 (the 7.11-7.13 hotfixes) is **untested**.
- **I could not test v7.10.0-pre1.** Running the downloaded binary from /tmp was refused by the session's permission classifier, so I did not run it and did not install it.
- Installed v7.04.1-pre3 against the installed build:
  - `scripts/nms-pak get 'gcrecipetable\.mbin$'` (NMS_PAK_WORK=/tmp/nms-pak-scratch-20261103) converts cleanly, as do difficultyconfig, gcskyglobals, humidweather and both interaction.entity files.
  - The extractor's set fails (see 3). These templates changed GUID (log: `raw/mbincompiler-extract-20261103.log`):

    | Template | Result |
    |---|---|
    | GcMissionTable | 27 files: exception, no MXML |
    | GcBaseBuildingTable | basebuildingobjectstable: exception, no MXML |
    | GcProductTable | 3 files, "File not recognized", MXML still written |
    | GcSubstanceTable | "File not recognized", MXML still written |
    | GcProceduralProductTable | "File not recognized", MXML still written |
    | GcGameplayGlobals | "File not recognized", MXML still written |

    Clean: the recipe, technology and procedural-technology tables, frigate traits, the reward table, fleet and environment globals, the hotspots table, the biome list and the language files.
- **Side effect:** MBINCompiler writes its log next to the binary, so my runs replaced `/opt/nmstools/MBINCompiler-linux.log`. The previous log was from 2026-10-30 23:44, on build 26308211. Before it was replaced I read it: the same failure, with 28 files failed and 35 warnings.
- `data/nms_mapping.json` is libMBIN 7.4.0.1 with 1,463 keys and is dated Sep 30. The 7.10.0-pre1 mapping.json is 7.10.0.1 with 1,496 keys: +33 keys, 0 removed, 0 changed. It is saved at /tmp/mbinc-7.10.0-pre1/mapping.json.
- `~/.cache/nms-exporter/mapping.json` does not exist, so the exporter uses data/nms_mapping.json (`MAPPING_CANDIDATES` in nmsexporter/nms.py).

### data/nms_tables.json is not what its meta says

- The meta reads build 25800958, generated 2026-10-19, MBINCompiler 7.04.1.3. The file was rewritten 2026-10-30 23:45, one minute after the failed 23:44 MBINCompiler run on 26308211.
- Its content carries `items.*.stack` on 978 items (937 products, 41 substances), and the matching `units["items.<id>.stack"]` entry sits **last** in `units`. The extractor would put that entry after `items.<id>.craft`.
- Those 978 values match, value for value, the StackMultiplier counts of the main product table as decoded by the GUID-mismatched 7.04.1-pre3 (175 of 0, 302 of 5, 382 of 10...). nms_basepartproducts is not included.
- So the file was most likely patched in place from a post-patch decode by a mismatched compiler, and the meta was never updated. The extractor itself exits on the MBINCompiler failure (`run()` -> `sys.exit`).
- Today's suspect decode gives the same stack values for every item that had one.

## 3. Table diff

`scripts/nms-extract-tables.py --work /tmp/nms-extract-20261103 --out /tmp/nms_tables_new.json` **failed**:

```
command failed: /opt/nmstools/MBINCompiler-linux convert -y --force -q /tmp/nms-extract-20261103/... (55 files)
exit=1   (MBINCompiler: "[INFO]: 28 FILES FAILED.", "[INFO]: 35 WARNINGS.")
```

As instructed, I did not retry it with another toolchain. To still get a diff, `raw/scripts/partial.py` calls the extractor's own parse functions on the MXMLs that did convert. It builds no missions, buildings or crops. Its output is **`/tmp/nms_tables_new.json`**, which is partial and not in the extractor's shape:
- Keys: `recipes`, `fleet`, `hotspots` (the parse_hotspots tuple), `biomes_by_star`, `labels`, `globals_SUSPECT`, `items_SUSPECT`, `status`.
- `meta.game_build_id` is 26331461.
- Sections marked SUSPECT come from templates whose GUID changed. They decode to sane values (every name and BaseValue of the 5,235 old items matches), but are not trusted.

Diff against data/nms_tables.json (`raw/diff.txt`, `raw/diff2.txt`):
- **meta build**: 25800958 -> 26331461.
- **recipes** (clean): 1,684 -> 1,684, **no recipe added, removed or changed**. `refiner.made_in_time` (suspect) is unchanged.
- **fleet** (clean): no differences. **extraction** hotspot classes, biome gases and substances (clean): identical. Falloff and survey distance: identical. **planets** biomes_by_star and labels (clean): identical.
- **items** (suspect): 5,235 -> 5,462; **227 added, 0 removed**.
  - 220 corvette BuildingParts:
    - cockpits B_COK_C1-C9 (Hornet/Viper/Mantis I-III-Class) and B_COK_E (Vantage);
    - habs and walkways B_HAB_D/E/F and B_HAB1_D/E/F (Legion/Gunner/Legionnaire);
    - hull sets B_STR_AC..AP_* (Basilisk, Reaper, Phantom, Blackthorn, Scorpion, Marrow, Webspinner...);
    - wings and thrusters B_WNG_S..Y (Gorgon, Dromedary, Komodo, Arthropod, Eldritch, Plated, Lockjaw), B_TRU_I/J (Arachnid Thruster, Razor Jet);
    - B_TUR_G (Dematerialisation Ray), B_GEN_6 (Chelone-Class Generator), B_LND_D, B_CON_16, B_DECO_U/V/W;
    - B_WALL_CANT0 and B_WALL_WIND3 (craftable);
    - GRAV_FLOOR, GRAV_RAMP, GRAV_WALL (25 LAND3 each).
  - Also SPOOK_PACKAGE1-6 (Preserved Brain/Grub/Sample/Eyeball/Egg/Horror, Curiosity, 140,000 u) and GRUB_HAT (Larva Tank).
  - **Renamed**:

    | Id | Old name | New name |
    |---|---|---|
    | HULK1 | Contaminated Metal | **Isotopic Dust** |
    | B_GEN_4 | Corvette Reactor Module | Limos-Class Generator |
    | B_GEN_5 | Corvette Reactor Module | Vile Proboscis Generator |
    | B_TUR_F | Corvette Weapon System | Venom Spitter |

  - **Values**: 0 changed. **Craft blueprints**: only the new items add any.
  - **stack**: 0 changes where the old file had a value. The new decode adds StackMultiplier for base parts from nms_basepartproducts (861 of 5, 543 of 0); the old file never read that table, so this is not a game change.
- **buildings, crops, missions**: not extracted (exception in MBINCompiler); no diff possible.

## 4. Save decode

- `curl localhost:9877/json`: `errors: {}`. The save is save4.hg, version 4745, Win|Final, Normal, written 2026-11-03 19:56 local on this build. `/healthz` is ok.
- `scripts/nms-decode-save.py save4.hg /tmp/patchcheck/save4.json` (and `--raw`) decodes cleanly. Of 975 distinct keys, 21 are not in data/nms_mapping.json. All 21 are in the 7.10 mapping and all sit in SeasonData barter UI (`raw/save-keys.txt`).
- The 125 save-key names the exporter code reads (`.get("X")` / `["X"]` matching mapping values) are **all present**. Nothing the exporter reads is missing or renamed.
- Content the old tables lack, already in the save:
  - 36 new corvette parts in `KnownProducts`. `/json` shows them as raw ids under `known.products`, for example B_COK_C1 and B_WNG_X.
  - New missions SPOOKSHOP_TUT, SPOOKSHOP_TUT_W, POI_HORROR and ABAND_SPOOKY (progress 4) are counted as "unknown" by `_missions`.
  - The current mission HAUL_TUT is in the old table, but 7.13 changed haulage missions.
  - HULK1 is shown as "Contaminated Metal" in 15 locations; the game now calls it "Isotopic Dust".

## 5. pyMHF hook

- Installed in the prefix: **nmspy 181442.1** with pymhf 0.2.5, built for NMS.exe 181442. **Installed exe is 184271.** PyPI has nmspy 183877.0 (Oct 29), 184069.0 (Oct 30) and **184271.0 (2026-10-31, requires pymhf[gui,http_api]==0.2.5)**, which matches the exe.
- Offline check, without launching the game (`raw/scripts/scan_patterns.py`): it parses `function_hook` byte patterns from types.py with `ast` and searches the exe's `.text` section.

  | | Unique | Multiple | Missing | Of |
  |---|---|---|---|---|
  | Installed 181442.1 vs new exe | 311 | 6 | 29 | 346 |
  | 184271.0 (wheel read as source, not installed) vs new exe | 344 | 4 | 8 | 356 |

  - live_position's hooks: cGcPlayerEnvironment.Update, cGcSky.SetStormState, cGcSky.Update and cGcPlanet.UpdateWeather resolve uniquely with both versions.
  - **visor_log is broken on 181442.1**: cGcBinoculars.UpdateTarget is ambiguous and cGcMarkerList.TryAddMarker is missing. Both resolve with 184271.0.
  - cGcGalaxyMap.Data (galaxy_log) is not a plain function_hook in types.py; not checked.
- Struct definitions live_position reads are unchanged between 181442.1 and 184271.0: cGcPlayerEnvironment, cGcSky, cGcPlanet, nmse cGcPlanetData/Weather/Hazard/UniverseAddressData, `mGameState` 0xE70, `mPlayerState` 0xAAD0, `mLocation` 0x860. cGcSimulation, cGcPlayer, cGcGameState and cGcPlayerState fields after `mPhotoModeSettings` did move. That is nmspy's view, not proof about the game layout.
- **What to change**:
  - In the prefix Python: `pip install nmspy==184271.0` (pymhf stays 0.2.5), using the same wine command as the 10-21 notes.
  - Update the version lines in scripts/nms-hook (header, lines 22-23) and pymhf_mods/visor_log.py (line 8).
  - Consider making `scripts/nms-hook --check` compare the exe's PE FileVersion to the installed nmspy major version. Today it only prints both.
  - **Until then, do not attach with visor_log loaded**: an unresolved hook is an injected-side error, and pyMHF 0.2.5 then SIGTERMs NMS.exe.

## 6. Knowledge concepts to re-cite

The cited game-data excerpts were compared with the same paths on 26331461 (`raw/cite-check*.txt`). **Every excerpt is unchanged at the same lines**:
- gcskyglobals L68-92 and humidweather L1276-1307 (weather-and-storms);
- the freighter plant-room floor0 and bioroom interaction.entity excerpts (harvest-all-radius, mechanic and data-location);
- regionhotspotstable L1-355 (extraction-hotspots);
- difficultyconfig L3845-3945 (refiner-capacity).

They can be re-cited on 26331461 with "unchanged". This is a flag only; I re-cited nothing. The loose `GAMEDATA/MODS/HarvestAllFreighter` override is still built on an unchanged base entity.

Concepts whose data could have changed and cannot yet be re-checked:
- **base-power** (cites data/nms_tables.json `buildings`): the base-building table does not decode. 7.10 also lets the Oxygen Harvester be built outside a base.
- **extraction-hotspots**: the table excerpt and the classes, gases and substances are unchanged. Re-cite once the tables regenerate, since `extraction` in data/nms_tables.json is from 25800958.
- **refiner-capacity** (measured on 26308211): the difficultyconfig excerpt is unchanged. The 4,095 output stop is a measurement, so re-measure if wanted.
- **save-coordinates, units-wallet** (measured on 25800958): no relevant notes and no save-key changes. Low risk; re-measure at leisure.

## 7. What might need to change in the exporter (priority order)

1. **Toolchain (blocks everything else)**: install MBINCompiler v7.10.0-pre1 into /opt/nmstools.
   - Test with `scripts/nms-pak get` on basebuildingobjectstable and coremissiontable: the log must show no "File not recognized" lines.
   - If it still fails on 26331461, wait for the next MBINCompiler release.
2. **Make `scripts/nms-extract-tables.py` `extract()` refuse GUID mismatches.**
   - MBINCompiler writes an MXML for a "File not recognized" template, so the parsers can read a mis-decoded table. Today that only stopped because other files threw and the exit code was non-zero.
   - Fix: parse the MBINCompiler log (it is beside the binary) for `File not recognized` / `FILES FAILED` and exit, and record the MBINCompiler version per table in meta.
3. **Regenerate data/nms_tables.json** with the fixed toolchain. Its meta is stale and its `stack` values came from a mismatched decode. That brings in:
   - the new items (names for `/json` `known.products` and `items`, used by `Collector._build`);
   - the rename HULK1 -> Isotopic Dust;
   - the 7.10/7.13 missions for `Collector._missions` (SPOOKSHOP_TUT, POI_HORROR, haulage variants);
   - a current `buildings`/`crops` for `power.base_power`, `Collector._bases`, `Collector.projected` and the Planner.
4. **Update the pyMHF side**: nmspy 184271.0 in the prefix, plus the version comments in scripts/nms-hook and pymhf_mods/visor_log.py. Do not load visor_log on 181442.1.
5. **Oxygen Harvesters outside bases (7.10)**.
   - Check in a save whether a harvester built outside a base appears anywhere the exporter reads: `Collector._bases`, `RESOURCE_KINDS`/`EXTRACTORS` in nmsexporter/nms.py, and scripts/nms-farm-check. If they are stored outside PersistentPlayerBases, farms will undercount.
   - Needs one in-game measurement; the notes do not say how they are saved.
6. **Refresh data/nms_mapping.json** from the 7.10.0-pre1 mapping.json (+33 keys). No exporter read depends on it today, but `scripts/nms-decode-save.py` output will show obfuscated barter keys until then.
7. **Corvette parts in the crafting and storage views**.
   - 220 new BuildingParts are bought with mementos, not crafted; only B_WALL_CANT0 and B_WALL_WIND3 carry a craft blueprint.
   - 6 memento Curiosities: check data/nms_storage_plan.json's Curiosity grouping, which sorts by `category`.
   - Once the base-part StackMultipliers are read, `CraftingModel.slot_cap` in nmsexporter/crafting.py will multiply product caps for base parts. Base parts are not refined, so this is low risk, but check the planner's storage maths.
8. **Knowledge**: once the tables regenerate, re-cite the concepts in section 6 on the new build (flag only here).

## Artefacts

- /tmp/nms_tables_new.json (partial, see 3); /tmp/nms-extract-20261103/ (unpacked MBINs/MXMLs);
  /tmp/nms-pak-scratch-20261103/ (nms-pak scratch work); /tmp/patchcheck/ (decoded save,
  exporter /json snapshot, scripts, web pages; nmspy wheels unpacked as source only, not
  installed or run); /tmp/mbinc-7.10.0-pre1/{report.json,mapping.json} (data files only).
