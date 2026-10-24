# nms-exporter

No Man's Sky save files as Prometheus metrics, with a Grafana dashboard.

The exporter reads the newest save in the Steam/Proton save directory, decodes
it, and serves `nms_*` metrics on `:9877`. It also serves the same snapshot as
JSON on `/json`. Standard library only; nothing to install.

Because the game only writes a save every few minutes, the save is treated as
an **anchor, not a feed**: refiners, extraction farms, plants and frigate
expeditions are projected forward on the wall clock from the save's own
timestamps at the game's rates, so the numbers keep moving between autosaves
and while the game is closed. A new save snaps everything back to the truth.

## What you get

| Area | Metrics |
|---|---|
| Right now | units, nanites, quicksilver, health, shield, life support, ship health, play time, save age, galactic address, the save summary text |
| Refiners | recipe matched from the slots; which base, freighter or corvette it is in; output and input amounts, progress, remaining time and finish time, projected |
| Extraction farms | fill level per extractor network from the extractor and depot objects, capacity, rate (measured from consecutive saves once possible, class-C assumed until then), time to full. A base with both mineral and gas extractors is two rows, depots going with the nearer cluster; the row is named from the substances in the base name ("Copper Oxygen"), since the save does not record what a hotspot yields |
| Plants | growth per plant, what each yields, ready-to-harvest count |
| Fleet | frigates by class; per expedition: departure, due back, progress, events done/failed, damaged frigates |
| Inventory | total and stack count per item across every container, and the amount per container for a "where is it" lookup |
| Lifetime | the ~470 counters from the save's stats block (`nms_stat{stat="DEATHS"}` and friends), collection counts |
| Crafting | per item: how many you can make now (all levels, crafting intermediates from stock through known routes), per-route one-level counts, ingredient needs and yields for every blueprint, refiner and cooking recipe, raw materials per unit, and the exact shortfall for one unit; `/json` adds the known blueprints you cannot make yet, grouped by the ingredient in the way |
| Missions | every mission in the save against the game's mission tables: in progress, complete or not started; for the ones in progress the current objective, stages left and what finishing hands out |
| Technology | what is installed in the exosuit, every multi-tool, ship, exocraft and the freighter, with a placement review: supercharged slots holding a fixed technology or nothing while an upgrade module sits on a plain slot, and modules not touching their stat family (the adjacency bonus). Module classes come from the save; their rolled stats do not, so the review is by class and family |

## Install

```bash
sudo ./install.sh                      # /opt/nms-exporter, systemd nms-exporter@<you>
curl -s localhost:9877/metrics | head
```

The unit runs as your user (it needs to read `~/.local/share/Steam/...`), with
`ProtectHome=read-only` and a state directory under `/var/lib/nms-exporter`
for the fill-level history that measured extraction rates come from.

Scrape it from Prometheus or VictoriaMetrics:

```yaml
- job_name: nms
  scrape_interval: 60s
  static_configs:
    - targets: ["<host>:9877"]
```

Environment overrides: `NMS_SAVE_DIR` (the `st_<steamid>` directory; found
automatically under the Proton prefix for app 275850), `NMS_EXPORTER_PORT`,
`NMS_EXPORTER_HOST`, `NMS_TABLES`, `NMS_MAPPING`, `NMS_STATE`.

## Grafana

Two dashboards in `grafana/`, both expecting a Prometheus-type datasource with
uid `prometheus`, both generated (edit the generator, not the JSON):

- `no-mans-sky.json` (`scripts/nms-grafana-dashboard.py`): status. Where you
  are with portal glyphs, currency, vitals, refiners with the base they are
  in, extraction farms, fleet with every frigate's base-roll score, inventory
  totals and locator, plants by kind with what they yield and your stock of
  it, missions in progress with objective and reward, the technology
  placement review, the storage tidy plan with its move list, what is almost
  craftable, lifetime counters. Portrait-first so it reads on a phone.
- `no-mans-sky-crafting.json` (`scripts/nms-grafana-crafting-dashboard.py`):
  what you can make. Pick an item and a quantity: ingredients per route with
  have/missing, raw materials with every intermediate expanded, the exact
  shortfall for one unit, what uses the item, and a table of everything you
  can make right now. Toggle known blueprints only, and filter by craft /
  refine / cook.

## Wall screens (conky)

Two portrait conky screens for monitors either side of the one the game runs
on, reading `/json` on loopback (`apt install conky-all`):

- `conky/left.conf` - the traveller: where the save says you are, currency,
  vitals, travel with the portal glyphs of the current system drawn as the
  game draws them (the glyph font in `conky/fonts/`, installed by
  `install.sh`) plus the galactic address, the frigate fleet with each expedition's progress and every frigate's
  base-roll score (stats less traits and rank-ups, as the community's frigate
  calculator does it), missions
  in progress (closest to done first, with the current objective and the
  reward), the technology placement review for the inventories with the most
  to gain, the collection and lifetime counters.
- `conky/right.conf` - the bases: refiners (running first, soonest done at the
  top, with the base they are in), extraction farms with fill and time to
  full, plants by kind with what they yield and how much is in stock, and the
  largest inventory stacks (click to search). The almost-craftable and tidy
  sections still render on demand but are left off the screen so the search
  stays in view.

Both carry the save's age, because every timer on them is projected from it.
Text is drawn at 0.8 of the design size so everything fits; `NMS_CONKY_TEXT_SCALE`
in the conky's environment changes that.

**Tidy storage.** `data/nms_storage_plan.json` says which storage container
each kind of item belongs in (by item id, id pattern, or the game's own item
category). The bases screen compares every stack in those containers with the
plan and lists, per container, what to bring in and from where, whether it will
have the slots, and what is doubled up and will merge. Move things in game and
the list shrinks on the next autosave. Edit the plan to taste; containers not
listed under `tidy` (exosuit, ships, freighter) are never asked to give
anything up.

**Inventory search.** Click the bases screen to search: a KDE box asks for
part of an item name, and the inventory panel shows every match with how much
is in each container. A name that matches a blueprint you know also lists that
blueprint's ingredients with how much you hold and which containers they are
in, so one search answers "can I craft this and where is the stuff". Right-click clears it (it also reverts after 15 minutes).
From a terminal: `conky/nms_search.py copper`, `conky/nms_search.py --clear`.
conky 1.22's own mouse hook never receives clicks under XInput2, so
`right.conf` starts `nms_search.py --watch`, which reads raw clicks from X
through ctypes and exits with conky. Needs `kdialog` for the search box.

```bash
sudo ./install.sh                         # also installs nms-conky@.service
./scripts/apply-kwin-rules.sh             # KDE: pin each window to its monitor
systemctl --user enable --now nms-conky@left nms-conky@right
```

Or just `conky -c conky/left.conf`. The leftmost and rightmost monitors are
used unless `NMS_CONKY_OUTPUT` names an output. The layout is 2160 x 3840
pixels, a rotated 4K panel as an X11 client sees it; `conky/palette.css` holds
the colours for both the configs and `conky/nms_conky.py`, the renderer.

On KDE the rules are needed, not decoration: KWin ignores an X11 window's
requested position, and clips X11 windows to `_NET_WORKAREA`, which a panel
on any monitor shortens. `kwin/nms-conky.kwinrule` forces position and
fullscreen by window class; its positions are holly's monitor layout, so check
yours as its header describes.

## Game data

`data/nms_tables.json` (not in git, it carries game text: build it from the installed game with `scripts/nms-extract-tables.py`) holds every refiner and cooking recipe with its time,
item names, extractor and hotspot constants, base-part rates, fleet timings
and the mission tables (title, stage objectives by progress number, rewards),
extracted from the installed game's `.pak` files so the numbers track the
installed build rather than a wiki. Regenerate after a game update:

```bash
scripts/nms-extract-tables.py          # needs hgpaktool + MBINCompiler, see the header
```

`data/nms_mapping.json` is the save key de-obfuscation table from the
[MBINCompiler](https://github.com/monkeyman192/MBINCompiler) release; the
exporter fetches a fresh one on first run if it can.

`scripts/nms-decode-save.py SAVE.hg out.json` dumps any save as readable JSON.

`scripts/nms-data item Methane` (also `recipes`, `uses`, `search`, `crops`, `biomes`,
`strings`) queries the extracted tables from the shell. The pak toolchain lives in
`/opt/nmstools` (hgpaktool, MBINCompiler-linux, a .NET 8 runtime); the extractor
defaults to it.

## Save backup to S3

Every save the game writes (and `accountdata.hg`) is uploaded with its `mf_`
manifest to the `nms-saves` bucket on Garage, keyed by the file's own mtime:
`<st_dir>/<stem>/<YYYYmmddTHHMMSSZ>/<stem>.hg` and `.../mf_<stem>.hg`. Garage has
no object versioning, so each version is its own key; uploads are idempotent.
The newest save of any slot is always at `current/save.hg`, `current/mf_save.hg`
and `current/info.json` (which slot file it is, its mtime, sha256 and versioned key),
overwritten in place.
Retention: everything for 7 days, the newest per hour to 30 days, the newest per
day after that (pruned every 6 hours). `nmsexporter/s3backup.py`, standard
library only (SigV4 checked against AWS's published examples).

Credentials live in OpenBao at `kv/garage/nms-saves` and reach the service as
`/etc/nms-exporter/s3.env` (root, mode 600), which the unit reads with
`EnvironmentFile=-`. `nms-bao-sync.timer` (boot + every 6h, root) keeps it current:
`scripts/nms-bao-sync.py` logs in with the `holly` AppRole (role_id/secret_id in
`/etc/nms-exporter/bao/`, root-only; secret_id never expires; token 15 min, revoked
after use), reads only that secret (policy `holly-nms-saves` in the homelab repo),
rewrites s3.env when it changed and restarts the exporter. The file looks like:

```
NMS_S3_ACCESS_KEY=GK...
NMS_S3_SECRET_KEY=...
# optional: NMS_S3_ENDPOINT=http://127.0.0.1:3900  NMS_S3_BUCKET=nms-saves  NMS_S3_REGION=garage
```

Status is in `/json` (`backup`) and `/metrics` (`nms_backup_*`). To restore: close
the game, turn Steam Cloud off for No Man's Sky, copy both files of a version
back into the save directory.

## Planner, history and the shell

- `/json` carries a `planner` section: how many Fusion Ignitors and Stasis Devices
  (`NMS_PLAN_TARGETS` to change) the stock builds right now and after one full
  harvest of the planted crops, with the ingredient blocking the next unit. The
  right wall screen shows it under the summary.
- `/diff?against=N` says what changed (units, items, farm fills) between the
  latest save and the one N saves earlier; the exporter keeps the last 48 saves
  in its state file.
- `/raw/bases` is the decoded `PersistentPlayerBases` list, for positional
  questions without a separate decode.
- `scripts/nms-rundown.py [--short|--diff]` prints the state as one screen, one
  line or a diff. `scripts/dev-deploy.sh [--render] [--test]` tests the working
  tree on :9878, optionally renders the right screen in Xvfb, installs to /opt
  and reloads the wall screens.
- `claude/nms-dash/` is a Claude Code plugin: `/nms`, `/nms diff`, `/deploy-nms`,
  the one-line state in the status line, and the opening state in the system
  prompt. Load it with `claude --plugin-dir claude/nms-dash` or by naming the
  folder in `CLAUDE_CODE_PLUGIN_DIRS`.

## Map

`http://<host>:9877/map` is a pan-and-zoom map (mouse, touch, pinch) built from
the save: each planet with its bases, exocraft, settlements and drained
deposits (distances true from the centre), and every base's layout from the
base computer - extractors, depots, power, pipes, wires and wire teleports -
with loose extractors flagged and listed. `?base=<name>` opens a base,
`?planet=<base name>` its planet. `/api/map` is the data behind it.

North is taken as the planet's +Y axis and is not yet checked against the
in-game compass; the page says so until it is.

## Phone page and Android app

`http://<host>:9877/mobile` is the phone-sized page: Map, Farms, Inventory and
Build, one tab at a time, built from the same `/api/map`, `/json` and
`/api/live` the map and the wall screens use (design: the "NMS Mobile" Claude
Design project; tokens from its Refined Midnight system, Geist fonts served from
`/fonts/`, the portal glyph font from `conky/fonts`).

- Map: the planet with its bases, exocraft and drained deposits, or a base's
  layout with pipes, wires and loose extractors flagged; pinch, drag, tap a mark
  for its card; the legend chips hide a kind; your live position and trail, a
  Nearby list and Go to arrows when the hook is reporting; the planet title
  opens the planet list.
- Farms: every extraction farm with its projected fill, time to full and loose
  count; a farm's page lists its extractors (tap one to see it on the layout)
  and the base's power verdict.
- Inventory: where everything is, per container; a search that matches a known
  blueprint also shows its ingredients with have/short and where they are.
- Build: the device planner, everything that can be made right now (`/json`
  `crafting.can_make`: the route the search chose and its ingredients against
  stock), and the almost-craftable list by the ingredient in the way. Tap any
  of them for every level of the build: an indented tree from the item down to
  raw materials, each line saying whether it comes from stock or is crafted,
  refined or cooked (and how many times), with a quantity stepper, what is
  short, and the raw materials it draws. `/api/craft?id=<id or name>&n=<units>`
  is the data: the same route choices as the crafting search, stock drawn down
  on a shared copy so an ingredient used in two branches is only counted once,
  surplus from rounding up to whole crafts returned for later branches. The
  item asked for is always made, never taken from stock.

The state is in the URL hash, so the browser's and the phone's back button step
back through it; `?base=` and `?planet=` open a view as on `/map`.

`android/` is the Android app: that page in a WebView, with what a browser
cannot give it: the screen stays on (a setting), the fold posture of a foldable
reaches the page (unfolded, the card lists go two-column with the gap on the
hinge; the page uses the viewport-segments media queries where the engine has
them and the shell's report otherwise), the exporter's address is remembered,
and it sits on the launcher. Built for a Pixel Fold; minSdk 29.

```bash
# once: an Android SDK (platform 36, build-tools 36) and a JDK 17
#   export ANDROID_HOME=~/Android/sdk   (android/local.properties: sdk.dir=...)
#   ~/.gradle/gradle.properties: org.gradle.java.home=/usr/lib/jvm/java-17-openjdk-amd64
cd android && ./gradlew assembleRelease        # app/build/outputs/apk/release/app-release.apk
adb install -r app/build/outputs/apk/release/app-release.apk
```

The release build is signed with the debug key so it installs without a
keystore of its own. On first start the app asks for the exporter's address
(`http://host:9877`); the App tab in the page reopens that dialog and the
keep-screen-on switch.

## Mechanics compendium and research

`knowledge/` is a sourced compendium of how the game works (mechanics, where
settings live in the game files, analysis tools); `research/` holds the open
questions, the stored sources every claim rests on, and research runs. Start at
`research/index.md` (charter and evidence ladder) and `knowledge/index.md`.

- `scripts/nms-pak find|get|grep|show|cite` - locate any of the ~195k packed
  paths, unpack and convert them, search them, and store an excerpt as a
  source under `research/sources/game-data/<build>/`.
- `scripts/nms-farm-check [base]` - extractors that are loose (not piped, no
  depot, no wire, never filled), with their position
  relative to the base computer and the nearest working network.
- `scripts/research-fetch URL --slug --why` - store a web page verbatim with
  provenance under `research/sources/web/`.
- `scripts/research-index` regenerates the question and concept indexes;
  `scripts/okf-lint` checks frontmatter and sources and flags concepts not yet
  re-checked on the installed build.
- `.claude/skills/deep-research/` is this repo's instance of the deep-research
  skill, with its workflow script.

Nothing under `knowledge/` or `research/` is installed to /opt.

## How it works

- `nmsexporter/nmssave.py` decodes the save: chunks of `<u32 0xFEEDA1E5><u32 comp><u32 uncomp><u32 0>` + a raw LZ4 block each, then key de-obfuscation.
- `nmsexporter/nms.py` builds the snapshot once per save change and applies the projection on every request.
- Refiner recipes: the slot with amount `-1` is the game's "chosen output" placeholder; otherwise the recipe whose ingredients exactly match the other slots wins.
- Extractor and depot fill levels live in the upper 32 bits of each base object's `UserData`, in link-grid units (1440 per item).
- Recipe seconds per operation = `TimeToMake / 250` for substances and `/ 2` for products (the game's `RefinerSubsMadeInTime` / `RefinerProductsMadeInTime`).
- Expedition length = events × 90 minutes from the fleet globals.
- Where a refiner is: `RefinerBufferKeys` are `GcMaintenanceSaveKey`, a
  position plus an integer `Location` with no enum in libMBIN. Read off a save:
  1 planet surface outside a base (planet coordinates, no address), 2 freighter,
  3 a planetary base, 5 space, 6 frigates, 8 corvette. Location 3 positions are
  relative to the base origin but on planet-aligned axes, so each base's
  refiner objects are rotated into that frame (Up = base position from the
  planet centre, Forward = the base's Forward made orthogonal) and matched
  within 2 units. Location 8 keys land on the corvette's `B_WALL_TECH0`
  modules. The same list carries damaged machinery, drop pods and frigate
  repair slots; those are skipped by their slot contents.
- Technology families: a procedural module's `Template` (T_JET, T_SHIPSHLD, ...)
  is itself a technology entry whose `BaseStat` names the stat family; fixed
  technologies carry their own. Supercharged slots are `SpecialSlots` of type
  `TechBonus`. `VehicleOwnership` is indexed by vehicle type: Roamer, Nomad,
  Colossus, Pilgrim, (unused), Nautilon, Minotaur.
- Missions: `MissionProgress.Progress` is a progress number, not a stage
  index; each stage's `Versions` table maps it per mission version, and
  `FinalStageVersions` gives the value a finished mission holds. The current
  objective is the last stage whose number is at or below the saved progress.
  Rewards are the mission's own reward entries, so they show what finishing
  the whole mission pays, not what the next step pays.
- Crafting: products expand through their blueprint; substances are treated
  as gathered and stop the tree, except the refined-only ones (chromatic
  metal, condensed carbon, pure and magnetised ferrite, ionised cobalt,
  deuterium, chlorine) which expand through their refiner recipe. Routes are
  chosen by what you hold most of, crafting on ties. "Can make" is a search
  over a simulation on a copy of the inventory, so shared bottlenecks count
  once. Recipes with the output among their own inputs (Oxygenate Carbon)
  are never used to expand that output.

Verified against a live save on 2026-09-30 (game build 25607545). Numbers
that depend on being present, such as expedition event outcomes, only change
when the game runs.
