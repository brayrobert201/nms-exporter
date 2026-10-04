#!/usr/bin/env python3
"""Conky renderer for two portrait No Man's Sky screens.

    nms_conky.py left  <section>    # the traveller: money, vitals, fleet, lifetime
    nms_conky.py right <section>    # the bases: refiners, farms, plants, inventory

Each call prints one section as conky markup; left.conf and right.conf stitch
the sections together with ${execpi}. Data is the exporter's own /json on
loopback, which is already projected forward from the save's timestamps, so
these screens keep moving between autosaves exactly like the metrics do.

Standard library only. Never raises: a dead exporter renders as an
explanation, not a blank screen or a traceback.
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
import urllib.request
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
URL = os.environ.get("NMS_CONKY_URL", "http://127.0.0.1:9877/json")
CACHE = Path(os.environ.get("XDG_RUNTIME_DIR", "/tmp")) / "nms-conky.json"
TTL = 4.0              # all sections of one refresh share a fetch
STALE_AFTER = 120.0    # past this, say the exporter is gone rather than show old numbers

# Canvas: a 2160 x 3840 portrait screen (4K rotated), 40 px margins.
MARGIN = 40
WIDTH = 2160 - 2 * MARGIN

SANS = "Noto Sans"
MONO = "DejaVu Sans Mono"
GLYPHS = "DejaVu Sans"         # Xft does no fallback, and Noto Sans lacks ● ▲ ✖
MONO_ADVANCE = 0.602           # DejaVu Sans Mono advance width, in ems


# ------------------------------------------------------------------ markup --

def _palette() -> dict:
    try:
        text = (HERE / "palette.css").read_text()
    except OSError:
        return {}
    return dict(re.findall(r"--([\w-]+):\s*#([0-9a-fA-F]{6})\b", text))


P = _palette()


def c(token: str) -> str:
    return "${color %s}" % P.get(token, "ffffff")


def font(px: int, bold: bool = False, mono: bool = False) -> str:
    return "${font %s:%spixelsize=%d}" % (MONO if mono else SANS, "bold:" if bold else "", px)


def glyph(ch: str, px: int = 28) -> str:
    return "${font %s:pixelsize=%d}%s%s" % (GLYPHS, px, ch, font(px))


def esc(s) -> str:
    return str(s).replace("$", "$$").replace("#", "\\#")


def _ok(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and v == v and abs(v) != float("inf")


def fnum(v, digits: int = 0) -> str:
    return f"{v:,.{digits}f}" if _ok(v) else "--"


def fbig(v) -> str:
    """188,291,752 -> 188.3M; small numbers stay exact."""
    if not _ok(v):
        return "--"
    for div, unit in ((1e9, "B"), (1e6, "M"), (1e3, "k")):
        if abs(v) >= div * 10:
            return f"{v / div:,.1f}{unit}"
    return f"{v:,.0f}"


def fdur(sec) -> str:
    if not _ok(sec):
        return "--"
    s = max(0, int(sec))
    d, h, m = s // 86400, (s % 86400) // 3600, (s % 3600) // 60
    if d:
        return f"{d}d {h}h"
    if h:
        return f"{h}h {m}m"
    if m:
        return f"{m}m"
    return f"{s}s"


def _n(n, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


def fkm(metres) -> str:
    return f"{metres / 1000:,.1f} km" if _ok(metres) else "--"


def fwhen(ts) -> str:
    if not _ok(ts):
        return "--"
    dt = datetime.fromtimestamp(ts)
    return dt.strftime("%H:%M") if dt.date() == datetime.now().date() else dt.strftime("%a %H:%M")


TONE_TOKEN = {"good": "good", "warning": "warning", "serious": "serious",
              "critical": "critical", "idle": "ink-muted"}
GLYPH = {"good": "●", "warning": "▲", "serious": "▲", "critical": "✖", "idle": "○"}


def pill(t: str, word: str, px: int = 28) -> str:
    """Status never rides on colour alone: glyph and word go with it."""
    return f"{c(TONE_TOKEN[t])}{glyph(GLYPH[t], px)} {esc(word)}"


def mag(frac, warn=0.75, serious=0.88, critical=0.95) -> str:
    """Magnitude colour: neutral blue until a threshold is actually crossed."""
    if not _ok(frac) or frac < warn:
        return "series-1"
    return "critical" if frac >= critical else "serious" if frac >= serious else "warning"


def bar(frac, colour: str, width: int = WIDTH, px: int = 18, x: int | None = None) -> str:
    cells = max(1, int(width / round(px * MONO_ADVANCE)))   # hinting snaps advances to whole px
    f = min(1.0, max(0.0, frac)) if _ok(frac) else 0.0
    n = round(f * cells)
    lead = "${goto %d}" % x if x is not None else ""
    return f"{lead}{font(px, mono=True)}{c(colour)}{'█' * n}{c('surface-2')}{'█' * (cells - n)}"


def header(title: str, right: str = "") -> str:
    out = f"{font(40, bold=True)}{c('ink-1')}{esc(title)}"
    if right:
        out += f"${{alignr}}{font(28)}{right}"
    return out + f"\n{c('axis')}${{voffset -6}}${{hr 2}}"


def columns(n: int) -> list[int]:
    return [MARGIN + i * (WIDTH // n) for i in range(n)]


def stats(items: list[tuple], n: int | None = None, value_px: int = 54) -> str:
    """Stat tiles: (label, value[, sub]) on evenly spaced columns."""
    cols = columns(n or len(items))
    lines = [
        "".join(f"${{goto {x}}}{font(26)}{c('ink-muted')}{esc(it[0])}" for x, it in zip(cols, items)),
        "".join(f"${{goto {x}}}{font(value_px, bold=True)}{c('ink-1')}{it[1]}" for x, it in zip(cols, items)),
    ]
    if any(len(it) > 2 and it[2] for it in items):
        lines.append("".join(f"${{goto {x}}}{font(26)}{c('ink-2')}{it[2] if len(it) > 2 else ''}"
                             for x, it in zip(cols, items)))
    return "\n".join(lines)


def _strip(s: str) -> str:
    return re.sub(r"\$\{[^}]*\}", "", s).replace("$$", "$").replace("\\#", "#")


def table(head: list[str], rows: list[list[str]], xs: list[int], right: set[int]) -> str:
    """Columns at fixed x; numeric columns right-aligned by monospace padding."""
    widths = [max([len(head[i])] + [len(_strip(r[i])) for r in rows]) for i in range(len(head))]

    def cell(i, text, colour, hdr=False):
        pad = " " * (widths[i] - len(_strip(text))) if i in right else ""
        f = font(28, mono=True) if i in right else font(26 if hdr else 30)
        return f"${{goto {xs[i]}}}{f}{c(colour)}{pad}{text}"

    out = ["".join(cell(i, esc(h), "ink-muted", True) for i, h in enumerate(head))]
    for r in rows:
        out.append("".join(cell(i, v, "ink-1" if i == 0 else "ink-2") for i, v in enumerate(r)))
    return "\n".join(out)


def note(text: str, t: str = "warning") -> str:
    return f"{font(28)}{c(TONE_TOKEN[t])}{glyph('⚠')} {c('ink-2')}{esc(text)}"


def empty(text: str) -> str:
    return f"{font(28)}{c('ink-muted')}{esc(text)}"


# -------------------------------------------------------------------- data --

def load() -> tuple[dict | None, str | None, float]:
    """(payload, error, age of the last good payload). One fetch per TTL;
    through a failure the last good payload shows until it is too old."""
    try:
        cached = json.loads(CACHE.read_text())
    except (OSError, ValueError):
        cached = {}
    now = time.time()
    if now - cached.get("fetched", 0) >= TTL:
        err, data, good = None, cached.get("data"), cached.get("good", 0)
        try:
            with urllib.request.urlopen(URL, timeout=3) as r:
                data, good = json.loads(r.read()), now
            data.pop("known", None)              # large and unused here
        except Exception as e:                   # noqa: BLE001 - never raise
            err = f"{type(e).__name__}: {e}"
        cached = {"fetched": now, "good": good, "error": err, "data": data}
        try:
            tmp = CACHE.with_name(f"{CACHE.name}.{os.getpid()}.tmp")
            tmp.write_text(json.dumps(cached))
            tmp.replace(CACHE)
        except OSError:
            pass
    good = cached.get("good", 0)
    age = now - good if good else float("inf")
    if not cached.get("data") or age > STALE_AFTER:
        return None, cached.get("error") or "no data", age
    return cached["data"], cached.get("error"), age


def masthead(d, err, age, subtitle: str) -> str:
    out = (f"{font(84, bold=True)}{c('ink-1')}No Man's Sky"
           f"{font(40)}{c('ink-muted')}  {subtitle}"
           f"${{alignr}}{font(30)}{c('ink-muted')}{datetime.now():%H:%M}\n"
           f"{c('axis')}${{hr 2}}")
    if not d:
        out += "\n" + note(f"exporter unreachable at {URL} - {err}", "critical")
    elif err:
        out += "\n" + note(f"showing data {fdur(age)} old - {err}")
    elif d.get("errors"):
        out += "\n" + "\n".join(note(f"{k}: {v}") for k, v in d["errors"].items())
    return out


def save_line(d) -> str:
    """Everything below is projected from the last save; say how old it is."""
    s = d.get("save") or {}
    age = s.get("age")
    t = "good" if _ok(age) and age < 900 else "idle"
    return (f"{font(26)}{c('ink-muted')}last save {fwhen(s.get('timestamp'))}  ·  "
            f"{pill(t, fdur(age) + ' ago', 26)}{c('ink-muted')}  ·  "
            f"timers projected from the save")


# ============================================================ left: traveller ==

def left_where(d) -> str:
    s = d.get("save") or {}
    mode = "  ·  ".join(x for x in (s.get("game_mode"), s.get("difficulty")) if x and x != "Normal")
    return (f"{font(26)}{c('ink-muted')}Where\n"
            f"{font(58, bold=True)}{c('ink-1')}{esc(s.get('summary') or '--')}"
            f"${{alignr}}{font(28)}{c('ink-2')}{esc(mode)}\n" + save_line(d))


def left_money(d) -> str:
    p = d.get("player") or {}
    st = d.get("stats") or {}
    return header("Currency") + "\n" + stats([
        ("Units", fbig(p.get("units")), f"{fbig(st.get('MONEY_EVER'))} earned ever"),
        ("Nanites", fnum(p.get("nanites")), f"{fbig(st.get('NANITES_EVER'))} earned ever"),
        ("Quicksilver", fnum(p.get("quicksilver"))),
    ], 3, value_px=72)


def left_vitals(d) -> str:
    p = d.get("player") or {}
    out = [header("Vitals")]
    for label, v in (("Health", p.get("health")), ("Shield", p.get("shield")),
                     ("Life support", p.get("energy"))):
        frac = v / 100 if _ok(v) else None
        # Low is the problem here, so the scale is inverted for the colour.
        colour = mag(1 - frac, warn=0.7, serious=0.8, critical=0.9) if _ok(frac) else "series-1"
        out.append(f"{font(30)}{c('ink-2')}{label}${{alignr}}{font(30, mono=True)}{c('ink-1')}{fnum(v)}")
        out.append(bar(frac, colour, px=16))
    hz = [h for h in (p.get("hazard") or []) if _ok(h) and h > 0]
    ammo = p.get("ammo") or {}
    out.append("${voffset 8}" + stats([
        ("Ship health", fnum(p.get("ship_health"))),
        ("Hazard", pill("warning", f"{max(hz):.0f}") if hz else f"{c('ink-2')}none"),
        ("Bolt ammo", fnum(ammo.get("bolt"))),
        ("Scatter ammo", fnum(ammo.get("scatter"))),
    ], value_px=44))
    return "\n".join(out)


def left_where_in(d) -> str:
    u = d.get("universe") or {}
    p = d.get("player") or {}
    st = d.get("stats") or {}
    return header("Travel") + "\n" + stats([
        ("Galaxy", fnum(u.get("galaxy")), f"system {fnum(u.get('system'))}  ·  planet {fnum(u.get('planet'))}"),
        ("Coordinates", f"{fnum(u.get('x'))}, {fnum(u.get('y'))}, {fnum(u.get('z'))}"),
        ("Play time", fdur(p.get("total_play_time")), f"{fnum(st.get('PLAY_SESSIONS'))} sessions"),
        ("This life", fdur(p.get("time_alive")), f"{fnum(st.get('DEATHS'))} deaths"),
    ], value_px=44)


def left_fleet(d) -> str:
    f = d.get("fleet") or {}
    exps = f.get("expeditions") or []
    out_n = sum(1 for e in exps if not e.get("returned"))
    classes = "  ·  ".join(f"{k} {v}" for k, v in sorted((f.get("frigate_classes") or {}).items(), key=lambda kv: -kv[1]))
    out = [header("Fleet", f"{c('ink-muted')}{fnum(f.get('frigates'))} frigates"),
           f"{font(28)}{c('ink-2')}{esc(classes)}" if classes else empty("no frigates")]
    if not exps:
        out.append(empty("no expeditions"))
        return "\n".join(out)
    out.append(f"${{voffset 6}}{font(28)}{c('ink-muted')}{out_n} out  ·  {len(exps) - out_n} back")
    for e in exps:
        back = bool(e.get("returned"))
        state = (pill("good", "back - debrief waiting") if back
                 else f"{c('ink-2')}back in {fdur(e.get('remaining_seconds'))}  ·  {fwhen(e.get('eta'))}")
        failed = e.get("events_failed") or 0
        hurt = (e.get("damaged") or 0) + (e.get("destroyed") or 0)
        detail = [f"{e.get('events_done', 0)}/{e.get('events', 0)} events",
                  f"{e.get('frigates', 0)} frigates"]
        tail = ""
        if failed:
            tail += f"  ·  {pill('warning', f'{failed} failed', 26)}"
        if hurt:
            tail += f"  ·  {pill('serious', f'{hurt} damaged', 26)}"
        out.append(f"${{voffset 4}}{font(34, bold=True)}{c('ink-1')}{esc(e.get('category', '?'))}"
                   f"{font(28)}{c('ink-muted')}  ·  {esc(e.get('duration', ''))}"
                   f"${{alignr}}{font(28)}{state}")
        out.append(bar(e.get("progress"), "series-1", px=14))
        out.append(f"{font(26)}{c('ink-muted')}{'  ·  '.join(detail)}{tail}")
    return "\n".join(out)


def left_collections(d) -> str:
    k = d.get("collections") or {}
    row1 = [("Ships", fnum(k.get("ships"))), ("Multi-tools", fnum(k.get("multitools"))),
            ("Exocraft", fnum(k.get("vehicles"))), ("Bases", fnum(k.get("bases"))),
            ("Settlements", fnum(k.get("settlements")))]
    row2 = [("Companions", fnum(k.get("pets"))), ("Eggs", fnum(k.get("eggs"))),
            ("Systems visited", fnum(k.get("visited_systems"))), ("Discoveries", fnum(k.get("discoveries"))),
            ("Products known", fnum(k.get("known_products")))]
    return header("Collection") + "\n" + stats(row1, 5, value_px=44) + "\n${voffset 6}" + stats(row2, 5, value_px=44)


def left_lifetime(d) -> str:
    st = d.get("stats") or {}
    row1 = [("Walked", fkm(st.get("DIST_WALKED"))), ("Flown", fkm(st.get("DIST_FLY"))),
            ("Jetpacked", fkm(st.get("DIST_JETPACK"))), ("Warps", fnum(st.get("DIST_WARP")))]
    row2 = [("Planets found", fnum(st.get("DISC_PLANETS"))), ("Creatures found", fnum(st.get("DISC_CREATURES"))),
            ("Words learnt", fnum(st.get("WORDS_LEARNT"))), ("Sentinels killed", fnum(st.get("SENTINEL_KILLS")))]
    return header("Lifetime") + "\n" + stats(row1, value_px=44) + "\n${voffset 6}" + stats(row2, value_px=44)


# ================================================================ right: bases ==

def right_summary(d) -> str:
    refs = d.get("refiners") or []
    running = [r for r in refs if r.get("active")]
    ready = [r for r in refs if not r.get("active") and (r.get("projected_output") or 0) > 0]
    farms = list((d.get("farms") or {}).values())
    filling = [f.get("full_in_seconds") for f in farms if _ok(f.get("full_in_seconds")) and f["full_in_seconds"] > 0]
    plants = list((d.get("plants") or {}).values())
    mature = sum(p.get("mature") or 0 for p in plants)
    total = sum(p.get("total") or 0 for p in plants)
    nxt = [r.get("remaining_seconds") for r in running if _ok(r.get("remaining_seconds"))]
    return save_line(d) + "\n${voffset 8}" + stats([
        ("Refiners running", fnum(len(running)), f"next done in {fdur(min(nxt))}" if nxt else "none running"),
        ("Ready to collect", fnum(len(ready)), f"of {len(refs)} refiners"),
        ("Farms full", f"{sum(1 for f in farms if (f.get('fill_ratio') or 0) >= 1)} / {len(farms)}",
         f"next full in {fdur(min(filling))}" if filling else "none filling"),
        ("Plants ready", f"{mature} / {total}"),
    ])


def right_refiners(d, show: int = 20) -> str:
    refs = d.get("refiners") or []
    out = [header("Refiners", f"{c('ink-muted')}projected")]
    if not refs:
        out.append(empty("no refiners in the save"))
        return "\n".join(out)
    # Running first, soonest done at the top; then finished, fullest first.
    refs = sorted(refs, key=lambda r: (not r.get("active"), r.get("remaining_seconds") or 0,
                                       -(r.get("projected_output") or 0)))
    rows = []
    for r in refs[:show]:
        ins = ", ".join(i.get("item", "?") for i in r.get("inputs") or [])
        left_in = sum(x for x in (r.get("projected_inputs") or []) if _ok(x))
        if r.get("active"):
            state = f"{c('series-1')}{bar(r.get('progress'), 'series-1', width=220, px=16)}{font(28, mono=True)}{c('ink-2')} {fdur(r.get('remaining_seconds'))}"
        elif (r.get("projected_output") or 0) > 0:
            state = pill("good", "ready")
        else:
            state = pill("idle", "empty")
        rows.append([f"{esc(r.get('output', '?'))}{font(24)}{c('ink-muted')}  from {esc(ins)}",
                     fnum(r.get("projected_output")), fnum(left_in), state])
    out.append(table(["Makes", "Output", "Input left", "State"], rows,
                     [MARGIN, MARGIN + 1000, MARGIN + 1300, MARGIN + 1620], {1, 2}))
    if len(refs) > show:
        out.append(empty(f"+ {len(refs) - show} more"))
    return "\n".join(out)


def right_farms(d) -> str:
    farms = sorted((d.get("farms") or {}).values(), key=lambda f: f.get("full_in_seconds") or 0)
    out = [header("Extraction farms", f"{c('ink-muted')}projected")]
    if not farms:
        out.append(empty("no extraction farms"))
        return "\n".join(out)
    for f in farms:
        frac = f.get("fill_ratio")
        full = _ok(frac) and frac >= 1
        state = (pill("warning", "full - collect") if full
                 else f"{c('ink-2')}full in {fdur(f.get('full_in_seconds'))}")
        rate = f"{fnum(f.get('rate_items_per_hour'))}/h {'measured' if f.get('rate_measured') else 'assumed C-class'}"
        out.append(f"{font(32, bold=True)}{c('ink-1')}{esc(f.get('base', '?'))}"
                   f"{font(26)}{c('ink-muted')}  ·  {esc(f.get('kind', ''))}  ·  {rate}"
                   f"${{alignr}}{font(28)}{state}")
        # Filling up is the point of a farm, so a full one is a to-do, not an alarm:
        # the bar stays blue and the pill carries the state.
        out.append(bar(frac, "series-1", px=16))
        out.append(f"{font(26)}{c('ink-muted')}{fnum(f.get('projected_items'))} / {fnum(f.get('capacity_items'))} items"
                   f"  ·  {_n(f.get('extractors', 0), 'extractor')}, {f.get('gas_extractors', 0)} gas,"
                   f" {_n(f.get('depots', 0), 'depot')}")
    return "\n".join(out)


def right_plants(d) -> str:
    bases = list((d.get("plants") or {}).values())
    out = [header("Plants")]
    if not bases:
        out.append(empty("nothing planted"))
        return "\n".join(out)
    rows = []
    for b in bases:
        waits = [p.get("ready_in_seconds") for p in b.get("plants") or []
                 if _ok(p.get("ready_in_seconds")) and p["ready_in_seconds"] > 0]
        kinds = sorted({p.get("plant", "?") for p in b.get("plants") or []})
        all_ready = (b.get("mature") or 0) >= (b.get("total") or 0) > 0
        rows.append([esc(b.get("base", "?")), esc(", ".join(kinds)), f"{b.get('mature', 0)} / {b.get('total', 0)}",
                     pill("good", "harvest") if all_ready else f"{c('ink-2')}next in {fdur(min(waits)) if waits else '--'}"])
    out.append(table(["Base", "Growing", "Ready", "State"], rows,
                     [MARGIN, MARGIN + 700, MARGIN + 1300, MARGIN + 1620], {2}))
    return "\n".join(out)


SEARCH = Path(os.environ.get("XDG_RUNTIME_DIR", "/tmp")) / "nms-conky-search.json"
SEARCH_FOR = 15 * 60       # a search reverts to the usual panel after this long


def _search() -> str:
    """The active search term, written by nms_search.py, or ''."""
    try:
        s = json.loads(SEARCH.read_text())
    except (OSError, ValueError):
        return ""
    return s.get("query", "") if time.time() - s.get("at", 0) < SEARCH_FOR else ""


def right_search(d, query: str, show: int = 10) -> str:
    q = query.lower()
    items = sorted(((k, v) for k, v in (d.get("items") or {}).items()
                    if q in (v.get("item") or "").lower() or q in k.lower()),
                   key=lambda kv: -(kv[1].get("total") or 0))
    out = [header(f"Inventory  ·  “{query}”",
                  f"{c('ink-muted')}{len(items)} found  ·  right-click to clear")]
    if not items:
        out.append(empty(f"nothing in the inventory matches “{query}”"))
        return "\n".join(out)
    where: dict[str, dict[str, int]] = {}
    for loc in d.get("locations") or []:
        per = where.setdefault(loc.get("id"), {})
        per[loc.get("location", "?")] = per.get(loc.get("location", "?"), 0) + (loc.get("amount") or 0)
    xs = columns(3)
    for key, it in items[:show]:
        out.append(f"${{voffset 6}}{font(34, bold=True)}{c('ink-1')}{esc(it.get('item', key))}"
                   f"{font(26)}{c('ink-muted')}  {esc(it.get('type', ''))}"
                   f"${{alignr}}{font(34, mono=True)}{c('ink-1')}{fnum(it.get('total'))}")
        places = sorted(where.get(key, {}).items(), key=lambda kv: -kv[1])
        for start in range(0, len(places), 3):
            out.append("".join(
                f"${{goto {x}}}{font(28)}{c('ink-2')}{esc(name if len(name) <= 26 else name[:25] + '…')}"
                f"${{goto {x + WIDTH // 3 - 220}}}{font(28, mono=True)}{c('ink-2')}{fnum(n):>9}"
                for x, (name, n) in zip(xs, places[start:start + 3])))
    if len(items) > show:
        out.append(empty(f"+ {len(items) - show} more - narrow the search"))
    return "\n".join(out)


def right_inventory(d, show: int = 24) -> str:
    query = _search()
    if query:
        return right_search(d, query)
    items = sorted((d.get("items") or {}).values(), key=lambda i: -(i.get("total") or 0))
    out = [header("Inventory", f"{c('ink-muted')}{len(items)} kinds  ·  "
                               f"{sum(i.get('stacks') or 0 for i in items)} stacks  ·  click to search")]
    if not items:
        out.append(empty("inventory empty"))
        return "\n".join(out)
    top = items[:show]
    half = (len(top) + 1) // 2
    xs = columns(2)
    for a, b in zip(top[:half], top[half:] + [None]):
        line = ""
        for x, it in ((xs[0], a), (xs[1], b)):
            if not it:
                continue
            line += (f"${{goto {x}}}{font(30)}{c('ink-1')}{esc(it.get('item', '?'))}"
                     f"{font(24)}{c('ink-muted')}  {_n(it.get('locations', 0), 'place')}"
                     f"${{goto {x + WIDTH // 2 - 280}}}{font(28, mono=True)}{c('ink-2')}{fnum(it.get('total')):>11}")
        out.append(line)
    if len(items) > show:
        out.append(empty(f"+ {len(items) - show} more kinds"))
    return "\n".join(out)


# conky multiplies ${goto}/${voffset}/${offset} by Xft.dpi / 96 (the config
# passes that factor in), so positions are divided by it here and land where
# they were laid out. Fonts are not scaled, which is why this matters.
DPI_SCALE = float(os.environ.get("CONKY_DPI_SCALE") or 1) or 1.0


def unscale(text: str) -> str:
    if DPI_SCALE == 1:
        return text
    return re.sub(r"\$\{(goto|voffset|offset) (-?\d+)\}",
                  lambda m: "${%s %d}" % (m[1], round(int(m[2]) / DPI_SCALE)), text)


# -------------------------------------------------------------------- main --

SECTIONS = {
    "left": {"where": left_where, "money": left_money, "vitals": left_vitals, "travel": left_where_in,
             "fleet": left_fleet, "collection": left_collections, "lifetime": left_lifetime},
    "right": {"summary": right_summary, "refiners": right_refiners, "farms": right_farms,
              "plants": right_plants, "inventory": right_inventory},
}
SUBTITLE = {"left": "traveller", "right": "bases"}


def main(argv: list[str]) -> int:
    if len(argv) != 3 or argv[1] not in SECTIONS:
        print("usage: nms_conky.py left|right <section>", file=sys.stderr)
        return 2
    screen, section = argv[1], argv[2]
    try:
        d, err, age = load()
        if section == "head":
            out = masthead(d, err, age, SUBTITLE[screen])
        elif d is None:
            out = ""                     # the masthead already says why
        else:
            out = SECTIONS[screen][section](d)
    except Exception as e:               # noqa: BLE001 - a bug shows, it doesn't blank
        out = note(f"{section}: {type(e).__name__}: {e}", "critical")
    sys.stdout.write(unscale(out) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
