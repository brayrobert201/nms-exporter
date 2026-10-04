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
| Refiners | recipe matched from the slots; output and input amounts, progress, remaining time and finish time, projected |
| Extraction farms | fill level per base from the extractor and depot objects, capacity, rate (measured from consecutive saves once possible, class-C assumed until then), time to full |
| Plants | growth per plant, ready-to-harvest count |
| Fleet | frigates by class; per expedition: departure, due back, progress, events done/failed, damaged frigates |
| Inventory | total and stack count per item across every container, and the amount per container for a "where is it" lookup |
| Lifetime | the ~470 counters from the save's stats block (`nms_stat{stat="DEATHS"}` and friends), collection counts |
| Crafting | per item: how many you can make now (all levels, crafting intermediates from stock through known routes), per-route one-level counts, ingredient needs and yields for every blueprint, refiner and cooking recipe, raw materials per unit, and the exact shortfall for one unit |

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

- `no-mans-sky.json` (`scripts/nms-grafana-dashboard.py`): status. Currency,
  vitals, refiners, extraction farms, fleet, inventory totals and locator,
  lifetime counters. Portrait-first so it reads on a phone.
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
  vitals, travel, the frigate fleet with each expedition's progress, the
  collection and lifetime counters.
- `conky/right.conf` - the bases: refiners (running first, soonest done at the
  top), extraction farms with fill and time to full, plants, and the largest
  inventory stacks.

Both carry the save's age, because every timer on them is projected from it.

**Inventory search.** Click the bases screen to search: a KDE box asks for
part of an item name, and the inventory panel shows every match with how much
is in each container. Right-click clears it (it also reverts after 15 minutes).
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

`data/nms_tables.json` holds every refiner and cooking recipe with its time,
item names, extractor and hotspot constants, base-part rates and fleet
timings, extracted from the installed game's `.pak` files so the numbers track
the installed build rather than a wiki. Regenerate after a game update:

```bash
scripts/nms-extract-tables.py          # needs hgpaktool + MBINCompiler, see the header
```

`data/nms_mapping.json` is the save key de-obfuscation table from the
[MBINCompiler](https://github.com/monkeyman192/MBINCompiler) release; the
exporter fetches a fresh one on first run if it can.

`scripts/nms-decode-save.py SAVE.hg out.json` dumps any save as readable JSON.

## How it works

- `nmsexporter/nmssave.py` decodes the save: chunks of `<u32 0xFEEDA1E5><u32 comp><u32 uncomp><u32 0>` + a raw LZ4 block each, then key de-obfuscation.
- `nmsexporter/nms.py` builds the snapshot once per save change and applies the projection on every request.
- Refiner recipes: the slot with amount `-1` is the game's "chosen output" placeholder; otherwise the recipe whose ingredients exactly match the other slots wins.
- Extractor and depot fill levels live in the upper 32 bits of each base object's `UserData`, in link-grid units (1440 per item).
- Recipe seconds per operation = `TimeToMake / 250` for substances and `/ 2` for products (the game's `RefinerSubsMadeInTime` / `RefinerProductsMadeInTime`).
- Expedition length = events × 90 minutes from the fleet globals.
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
