#!/usr/bin/env python3
"""Conky renderer for two portrait No Man's Sky screens.

    nms_conky.py left  <section>    # the traveller: money, vitals, fleet, missions, technology, lifetime
    nms_conky.py right <section>    # the bases: refiners, farms, plants, inventory (crafting and tidy exist but are off the screen)
                                    # in crafting mode (/json crafting_mode, set from the phone) the same sections
                                    # draw the refinery board: every refiner's load, what to add, stock and output
    nms_conky.py right slot<N>      # the Nth panel of the right screen for the activity set from the phone
                                    # (/json activity): idle puts the inventory first, gathering the farms and
                                    # plants, crafting the refinery board, mission the focus mission's
                                    # stages (/json missions.focus) and the rest in progress (LAYOUT below)

Each call prints one section as conky markup; left.conf and right.conf stitch
the sections together with ${execpi}. Data is the exporter's own /json on
loopback, which is already projected forward from the save's timestamps, so
these screens keep moving between autosaves exactly like the metrics do.

Standard library only. Never raises: a dead exporter renders as an
explanation, not a blank screen or a traceback.
"""
from __future__ import annotations

import fcntl
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
PORTAL_FONT = "NMS Glyphs:style=Glyphs-Mono"   # conky/fonts/NMS-Glyphs-Mono.ttf, 0-9 A-F are the portal symbols
MONO_ADVANCE = 0.602           # DejaVu Sans Mono advance width, in ems
# Every font size below is a design size at 1.0; the screens carry more rows
# than that leaves room for, so text is scaled down. NMS_CONKY_TEXT_SCALE overrides.
TEXT_SCALE = float(os.environ.get("NMS_CONKY_TEXT_SCALE") or 0.8)


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


def _px(px: int) -> int:
    return max(10, round(px * TEXT_SCALE))


def font(px: int, bold: bool = False, mono: bool = False) -> str:
    return "${font %s:%spixelsize=%d}" % (MONO if mono else SANS, "bold:" if bold else "", _px(px))


def glyph(ch: str, px: int = 28) -> str:
    return "${font %s:pixelsize=%d}%s%s" % (GLYPHS, _px(px), ch, font(px))


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
    cells = max(1, int(width / round(_px(px) * MONO_ADVANCE)))   # hinting snaps advances to whole px
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

def _read_cache() -> dict:
    try:
        return json.loads(CACHE.read_text())
    except (OSError, ValueError):
        return {}


def _fetch() -> None:
    """One fetch of the payload into the cache file (atomic replace); never raises."""
    cached = _read_cache()
    now = time.time()
    err, data, good = None, cached.get("data"), cached.get("good", 0)
    try:
        with urllib.request.urlopen(URL, timeout=3) as r:
            data, good = json.loads(r.read()), now
        data.pop("known", None)              # large and unused here
    except Exception as e:                   # noqa: BLE001 - never raise
        err = f"{type(e).__name__}: {e}"
    try:
        tmp = CACHE.with_name(f"{CACHE.name}.{os.getpid()}.tmp")
        tmp.write_text(json.dumps({"fetched": now, "good": good, "error": err, "data": data}))
        tmp.replace(CACHE)
    except OSError:
        pass


def _refresh_in_background() -> None:
    """conky runs ${execpi} on its main loop, so a slow exporter would freeze the whole
    screen. The section renders from the cache at once and a detached child refreshes
    it; a lock keeps a dozen sections from starting a dozen fetches."""
    lock = os.open(CACHE.with_suffix(".lock"), os.O_CREAT | os.O_RDWR, 0o600)
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        os.close(lock)
        return                               # a refresh is already running
    if os.fork():
        os.close(lock)                       # parent: the child holds it
        return
    try:                                     # child: detach and fetch
        os.setsid()
        devnull = os.open(os.devnull, os.O_RDWR)
        for fd in (0, 1, 2):
            os.dup2(devnull, fd)
        _fetch()
    finally:
        os._exit(0)


def load() -> tuple[dict | None, str | None, float]:
    """(payload, error, age of the last good payload). One fetch per TTL, in the
    background once there is something to show; through a failure the last good
    payload shows until it is too old."""
    cached, now = _read_cache(), time.time()
    if not cached.get("data") or now - cached.get("good", 0) > STALE_AFTER:
        _fetch()                             # nothing worth showing yet: wait for it
        cached, now = _read_cache(), time.time()
    elif now - cached.get("fetched", 0) >= TTL:
        _refresh_in_background()
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
        # a small hazard still rounds to "0" at .0f; one decimal below 10 keeps the pill honest
        ("Hazard", pill("warning", f"{max(hz):.1f}" if max(hz) < 10 else f"{max(hz):.0f}") if hz else f"{c('ink-2')}none"),
        ("Bolt ammo", fnum(ammo.get("bolt"))),
        ("Scatter ammo", fnum(ammo.get("scatter"))),
    ], value_px=44))
    return "\n".join(out)


def left_where_in(d) -> str:
    u = d.get("universe") or {}
    p = d.get("player") or {}
    st = d.get("stats") or {}
    glyphs = u.get("glyphs") or ""
    # The portal code as the game draws it: the glyph font maps 0-9 A-F to the
    # sixteen symbols. The hex form sits under it for typing or sharing.
    glyph_row = (f"${{font {PORTAL_FONT}:pixelsize={_px(84)}}}{esc(glyphs)}{font(26)}" if glyphs
                 else f"{font(44, bold=True)}--")
    return header("Travel") + "\n" + stats([
        ("Portal glyphs", glyph_row,
         f"{font(28, mono=True)}{c('ink-2')}{esc(glyphs or '--')}{font(26)}{c('ink-muted')}  ·  galaxy {fnum(u.get('galaxy'))}  ·  system {fnum(u.get('system'))}  ·  planet {fnum(u.get('planet'))}"),
        ("Galactic address", f"{font(60, bold=True, mono=True)}{esc(u.get('address') or '--')}",
         f"voxel {fnum(u.get('x'))}, {fnum(u.get('y'))}, {fnum(u.get('z'))}"),
    ], 2, value_px=84) + "\n${voffset 6}" + stats([
        ("Play time", fdur(p.get("total_play_time")), f"{fnum(st.get('PLAY_SESSIONS'))} sessions"),
        ("This life", fdur(p.get("time_alive")), f"{fnum(st.get('DEATHS'))} deaths"),
        ("Warps", fnum(st.get("DIST_WARP"))), ("Systems visited", fnum((d.get("collections") or {}).get("visited_systems"))),
    ], 4, value_px=44)


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
    roster = f.get("roster") or []
    if roster:
        # Base roll per frigate, NMSCD's frigate-calculator formula: stats less
        # traits and rank-ups. 14 is the best roll the game makes, -5 the worst.
        rows = []
        for r in roster:
            sc = r.get("score")
            tone = "good" if _ok(sc) and sc >= 10 else "idle" if _ok(sc) and sc >= 5 else "warning"
            st = r.get("stats") or {}
            rows.append([f"{esc(r.get('name', '?'))}{font(24)}{c('ink-muted')}  {esc(r.get('race', ''))}",
                         esc(r.get("type", "?")), esc(r.get("inventory_class", "?")),
                         f"{fnum(st.get('combat'))}/{fnum(st.get('exploration'))}/{fnum(st.get('industrial'))}/{fnum(st.get('trade'))}",
                         fnum(r.get("level")), fnum(r.get("expeditions")),
                         pill(tone, f"{sc:+d}" if _ok(sc) else "--", 24)])
        out.append("${voffset 6}" + table(["Frigate", "Type", "Class", "Cbt/Exp/Ind/Trd", "Rank", "Trips", "Roll"], rows,
                                            [MARGIN, MARGIN + 560, MARGIN + 860, MARGIN + 1000, MARGIN + 1340, MARGIN + 1500, MARGIN + 1680], {4, 5}))
    return "\n".join(out)


def left_missions(d, show: int = 6) -> str:
    """Missions in progress, the one closest to finishing first: current objective
    and what completing it hands out, from the game's mission tables."""
    m = d.get("missions") or {}
    rows = m.get("in_progress") or []
    k = m.get("counts") or {}
    out = [header("Missions", f"{c('ink-muted')}{fnum(k.get('in_progress'))} in progress  ·  "
                              f"{fnum(k.get('complete'))} done  ·  closest to done first")]
    if not m.get("tables"):
        out.append(empty("no mission tables in data/nms_tables.json - run scripts/nms-extract-tables.py"))
        return "\n".join(out)
    if not rows:
        out.append(empty("no missions in progress"))
        return "\n".join(out)
    for r in rows[:show]:
        tag = f"  {pill('idle', 'selected', 24)}" if r.get("selected") else ""
        prog, final = r.get("progress"), r.get("final")
        step = f"stage {fnum(prog + 1)} of {fnum(final)}" if _ok(prog) and _ok(final) else ""
        out.append(f"${{voffset 6}}{font(32, bold=True)}{c('ink-1')}{esc(r.get('title', '?'))}{tag}"
                   f"${{alignr}}{font(28, mono=True)}{c('ink-2')}{step}")
        objective = r.get("objective") or "in progress"
        line = f"{font(26)}{c('ink-2')}{esc(objective[:90])}"
        if r.get("rewards"):
            reward = ", ".join(r["rewards"][:3])
            room = 150 - len(objective[:90])
            if len(reward) > room:
                reward = reward[:max(0, room - 1)] + "…"
            line += f"{c('ink-muted')}  ·  for {esc(reward)}"
        out.append(line)
    if len(rows) > show:
        out.append(empty(f"+ {len(rows) - show} more in progress"))
    return "\n".join(out)


def left_tech(d, show: int = 4) -> str:
    """Installed technology, placement first: the inventories with the most to
    gain from moving a module onto a supercharged slot or next to its family."""
    rows = [t for t in (d.get("tech") or []) if t.get("installed")]
    out = [header("Technology", f"{c('ink-muted')}supercharged slots and stat families  ·  from the save")]
    if not rows:
        out.append(empty("no technology in the save"))
        return "\n".join(out)

    def gain(t):
        return (len(t.get("move_in") or []) + len(t.get("upgrade") or []) + min(3, len(t.get("isolated") or []))
                + (3 if t.get("primary") else 0) + (2 if t.get("broken") else 0))
    rows.sort(key=lambda t: (-gain(t), t.get("inventory", "")))
    for t in rows[:show]:
        sc, good = t.get("supercharged") or 0, t.get("supercharged_good") or 0
        sc_text = (f"{good} of {sc} supercharged slots carry a module" if sc else "no supercharged slots")
        state = pill("good", "well placed", 26) if not (t.get("move_in") or t.get("upgrade") or t.get("isolated")) \
            else pill("warning", f"{len(t.get('move_in') or []) + len(t.get('upgrade') or [])} to move", 26) if (t.get("move_in") or t.get("upgrade")) \
            else pill("idle", "families split", 26)
        out.append(f"${{voffset 6}}{font(32, bold=True)}{c('ink-1')}{esc(t.get('inventory', '?'))}"
                   f"{font(26)}{c('ink-muted')}  ·  {esc(t.get('class') or '?')}-class  ·  {fnum(t.get('installed'))} installed"
                   f"  ·  {sc_text}" + (f"  ·  {pill('serious', str(t['broken']) + ' broken', 26)}" if t.get("broken") else "")
                   + f"${{alignr}}{font(28)}{state}")
        lines = []
        if t.get("move_in"):
            swap = f" instead of {', '.join(t['move_out'])}" if t.get("move_out") else ""
            lines.append(f"supercharge {', '.join(t['move_in'][:3])}{swap}")
        if t.get("upgrade"):
            lines.append(f"better than what is supercharged: {', '.join(t['upgrade'][:2])}")
        iso = t.get("isolated") or []
        if iso:
            fams: dict[str, int] = {}
            for i in iso:
                fams[i.get("family_name", "?")] = fams.get(i.get("family_name", "?"), 0) + 1
            lines.append("not touching their family: " + ", ".join(f"{n} {fam}" for fam, n in list(fams.items())[:3]))
        for line in lines[:2]:
            out.append(f"{font(26)}{c('ink-2')}{esc(line[:150])}")
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

def _ref_state(r: dict) -> str:
    """run | full (output at its cap with input left) | ready (output to collect) | empty."""
    if r.get("active"):
        return "run"
    ins = zip(r.get("projected_inputs") or [], r.get("inputs") or [])
    if r.get("stalls_at_cap") and any(_ok(h) and h >= (i.get("per_op") or 1) for h, i in ins):
        return "full"
    return "ready" if (r.get("projected_output") or 0) > 0 else "empty"


_REF_ORDER = {"run": 0, "full": 1, "ready": 2, "empty": 3}


def _refs(d) -> list:
    """Refiners in working order: running (soonest done first), full, ready (fullest first), empty."""
    refs = [dict(r, state=_ref_state(r)) for r in d.get("refiners") or []]
    return sorted(refs, key=lambda r: (_REF_ORDER[r["state"]], r.get("remaining_seconds") or 0 if r["state"] == "run" else 0,
                                       -(r.get("projected_output") or 0), r.get("output") or ""))


def _ref_pill(r: dict, bar_px: int = 220) -> str:
    if r["state"] == "run":
        return f"{c('series-1')}{bar(r.get('progress'), 'series-1', width=bar_px, px=16)}{font(28, mono=True)}{c('ink-2')} {fdur(r.get('remaining_seconds'))}"
    if r["state"] == "full":
        return pill("warning", "full - empty it")      # output slot at its cap with inputs left
    if r["state"] == "ready":
        return pill("good", "ready")
    return pill("idle", "empty")


# ------------------------------------------- the refinery board (crafting mode) --
# Set from the phone (POST /api/mode {"crafting": true}) for a bulk crafting session; the
# exporter keeps it and /json says crafting_mode. The right screen's sections then draw the
# refinery instead of farms and plants: the planner and the inventory search stay.

def refinery_summary(d) -> str:
    refs = _refs(d)
    by = {k: [r for r in refs if r["state"] == k] for k in _REF_ORDER}
    nxt = [r.get("remaining_seconds") for r in by["run"] if _ok(r.get("remaining_seconds"))]
    fills = [i for r in refs for i in (r.get("to_fill") or {}).get("inputs") or []]
    adds, spare = sum(i.get("add") or 0 for i in fills), sum(i.get("spare") or 0 for i in fills)
    return (save_line(d) + f"{c('ink-muted')}  ·  {pill('good', 'crafting mode', 26)}{c('ink-muted')}  ·  turn off on the phone"
            + "\n${voffset 8}" + stats([
                ("Running", fnum(len(by["run"])), f"next done in {fdur(min(nxt))}" if nxt else "none running"),
                ("Full - empty it", fnum(len(by["full"])), "output at its cap, input left"),
                ("Ready to collect", fnum(len(by["ready"])), f"of {len(refs)} refiners  ·  {len(by['empty'])} empty"),
                ("To add", fnum(adds), f"units over every refiner  ·  {fnum(spare)} spare to take out"),
            ]))


def refinery_board(d) -> str:
    """Every refiner on two lines: what it makes and where, then the output now and at the
    end of the run against the slot's cap, each input with what to add (or take out) so the
    run ends exactly at the cap, and the optimum load for that refiner."""
    refs = _refs(d)
    out = [header("Refinery board", f"{c('ink-muted')}{_n(len(refs), 'refiner')}  ·  what to add, where each run ends  ·  projected")]
    if not refs:
        out.append(empty("no refiners in the save"))
        return "\n".join(out)
    for r in refs:
        ins = r.get("inputs") or []
        names = " + ".join(i.get("item", "?") for i in ins)
        ratio = " + ".join(str(i.get("per_op", "?")) for i in ins) + f" -> {r.get('output_per_op', '?')}"
        out.append(f"${{voffset 6}}{font(32, bold=True)}{c('ink-1')}{esc(r.get('output', '?'))}"
                   f"{font(26)}{c('ink-muted')}  from {esc(names)}  ·  {esc(r.get('base') or '?')}  ·  {esc(r.get('recipe', ''))}  ·  {esc(ratio)}"
                   f"${{goto {MARGIN + 1700}}}{font(28)}{_ref_pill(r)}")
        parts = [f"{c('ink-2')}output {c('ink-1')}{fnum(r.get('projected_output'))}{c('ink-2')} now, "
                 f"{c('ink-1')}{fnum(r.get('end_output'))}{c('ink-2')} at end, cap {fnum(r.get('output_cap'))}"]
        fill = {i["id"]: i for i in (r.get("to_fill") or {}).get("inputs") or []}
        for i, have in zip(ins, r.get("projected_inputs") or []):
            f = fill.get(i.get("id")) or {}
            t = f"{c('ink-2')}{esc(i.get('item', '?'))} {c('ink-1')}{fnum(have)}"
            if f.get("add"):
                t += f"{c('good')}  add {fnum(f['add'])}"
            elif f.get("spare"):
                t += f"{c('warning')}  take out {fnum(f['spare'])}"
            parts.append(t)
        opt = r.get("optimum") or {}
        if opt.get("inputs"):
            load = " + ".join(f"{fnum(i.get('amount'))} {i.get('item', '?')}" for i in opt["inputs"])
            parts.append(f"{c('ink-muted')}optimum {esc(load)} -> {fnum(opt.get('output'))}")
        out.append(f"${{goto {MARGIN + 40}}}{font(26)}" + f"{c('ink-muted')}  ·  ".join(parts))
    return "\n".join(out)


def _where(d, iid: str, n: int = 2) -> str:
    """The containers holding most of an item (every stack in a container summed)."""
    per: dict = {}
    for l in d.get("locations") or []:
        if l.get("id") == iid:
            per[l.get("location", "?")] = per.get(l.get("location", "?"), 0) + (l.get("amount") or 0)
    top = sorted(per.items(), key=lambda kv: -kv[1])[:n]
    return ", ".join(f"{where} {fnum(amt)}" for where, amt in top) or "none anywhere"


def refinery_stock(d) -> str:
    """The inputs the loaded recipes take: in stock and where, loaded already, what the
    top-ups need and how far stock falls short."""
    refs = d.get("refiners") or []
    items = d.get("items") or {}
    agg: dict = {}
    for r in refs:
        fill = {i["id"]: i for i in (r.get("to_fill") or {}).get("inputs") or []}
        for i, have in zip(r.get("inputs") or [], r.get("projected_inputs") or []):
            a = agg.setdefault(i.get("id"), {"item": i.get("item", "?"), "loaded": 0, "add": 0, "spare": 0, "refiners": 0})
            f = fill.get(i.get("id")) or {}
            a["loaded"] += have if _ok(have) else 0
            a["add"] += f.get("add") or 0
            a["spare"] += f.get("spare") or 0
            a["refiners"] += 1
    out = [header("Refinery stock", f"{c('ink-muted')}what the loaded recipes take  ·  stock against the top-ups")]
    if not agg:
        out.append(empty("no refiner has a recipe loaded"))
        return "\n".join(out)
    rows = []
    for iid, a in sorted(agg.items(), key=lambda kv: (-max(0, kv[1]["add"] - ((items.get(kv[0]) or {}).get("total") or 0)), -kv[1]["add"])):
        stock = (items.get(iid) or {}).get("total") or 0
        short = max(0, a["add"] - stock)
        rows.append([f"{esc(a['item'])}{font(24)}{c('ink-muted')}  {_n(a['refiners'], 'refiner')}", fnum(stock), esc(_where(d, iid)),
                     fnum(a["loaded"]), fnum(a["add"]), f"{c('warning')}{fnum(short)}" if short else f"{c('ink-muted')}--",
                     fnum(a["spare"]) if a["spare"] else f"{c('ink-muted')}--"])
    out.append(table(["Input", "In stock", "Where", "Loaded", "To add", "Short", "Spare"], rows,
                     [MARGIN, MARGIN + 400, MARGIN + 620, MARGIN + 1240, MARGIN + 1440, MARGIN + 1640, MARGIN + 1840], {1, 3, 4, 5, 6}))
    return "\n".join(out)


def refinery_output(d) -> str:
    """What the refiners hold of each product now and at the end of their runs, the room
    left under the caps, and the stock already in hand."""
    refs = d.get("refiners") or []
    items = d.get("items") or {}
    agg: dict = {}
    for r in refs:
        a = agg.setdefault(r.get("output_id"), {"item": r.get("output", "?"), "now": 0, "end": 0, "cap": 0, "refiners": 0, "opt": []})
        a["now"] += r.get("projected_output") or 0
        a["end"] += r.get("end_output") or 0
        a["cap"] += r.get("output_cap") or 0
        a["refiners"] += 1
        a["opt"].append((r.get("optimum") or {}).get("output") or 0)
    out = [header("Refined output", f"{c('ink-muted')}in the refiners now and at the end of the runs  ·  against stock")]
    if not agg:
        out.append(empty("no refiner has a recipe loaded"))
        return "\n".join(out)
    rows = []
    for iid, a in sorted(agg.items(), key=lambda kv: -kv[1]["end"]):
        opts = sorted(set(a["opt"]))
        per_load = fnum(opts[0]) if len(opts) == 1 else f"{fnum(opts[0])} to {fnum(opts[-1])}"
        rows.append([esc(a["item"]), fnum(a["refiners"]), fnum(a["now"]), fnum(a["end"]), fnum(a["cap"]), per_load,
                     fnum((items.get(iid) or {}).get("total") or 0)])
    out.append(table(["Output", "Refiners", "Now", "At end", "Caps", "Per load", "In stock"], rows,
                     [MARGIN, MARGIN + 520, MARGIN + 760, MARGIN + 1000, MARGIN + 1240, MARGIN + 1480, MARGIN + 1800], {1, 2, 3, 4, 5, 6}))
    return "\n".join(out)


def right_summary(d) -> str:
    if d.get("crafting_mode"):
        return refinery_summary(d)
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


def right_planner(d) -> str:
    """What the stock builds right now and after one full harvest, per target,
    with the ingredient standing in the way of the next unit."""
    p = d.get("planner") or {}
    out = [header("Device planner", f"{c('ink-muted')}known blueprints, from stock")]
    if not p.get("targets"):
        out.append(empty("no planner data"))
        return "\n".join(out)
    def counts(run: dict) -> str:
        names = run.get("names") or {}
        parts = [f"{n} {names.get(t, t)}" for t, n in (run.get("counts") or {}).items() if n]
        return esc(", ".join(parts)) if parts else "nothing"

    best, after = p.get("best_now") or {}, p.get("best_after_harvest") or {}
    out.append(stats([("Craftable now", counts(best), f"worth {fbig(best.get('value'))}"),
                      ("After a full harvest", counts(after), f"worth {fbig(after.get('value'))}")], 2, value_px=40))
    for t in p["targets"]:
        b = t.get("blocker")
        blk = f"next one needs {b['item']}, {fnum(b['have'])} of {fnum(b['need'])}" if b else "nothing in the way"
        out.append(f"{font(28)}{c('ink-1')}{esc(t['item'])}{c('ink-muted')}  ·  now {t['now']}"
                   f"  ·  after harvest {t['after_harvest']}  ·  {esc(blk)}")
    return "\n".join(out)


def right_refiners(d, show: int = 10) -> str:
    if d.get("crafting_mode"):
        return refinery_board(d)
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
        elif r.get("stalls_at_cap") and r.get("ops_remaining"):
            state = pill("warning", "full - empty it")      # output slot at its cap with inputs left
        elif (r.get("projected_output") or 0) > 0:
            state = pill("good", "ready")
        else:
            state = pill("idle", "empty")
        rows.append([f"{esc(r.get('output', '?'))}{font(24)}{c('ink-muted')}  from {esc(ins)}",
                     esc(r.get("base") or "?"), fnum(r.get("projected_output")), fnum(left_in), state])
    out.append(table(["Makes", "Where", "Output", "Input left", "State"], rows,
                     [MARGIN, MARGIN + 720, MARGIN + 1160, MARGIN + 1400, MARGIN + 1660], {2, 3}))
    if len(refs) > show:
        out.append(empty(f"+ {len(refs) - show} more"))
    return "\n".join(out)


def right_farms(d) -> str:
    if d.get("crafting_mode"):
        return refinery_stock(d)
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
        name = f.get("name") or f.get("base") or "?"
        where = f"  ·  {esc(f['base'])}" if f.get("base") and f["base"] != name else ""
        out.append(f"{font(32, bold=True)}{c('ink-1')}{esc(name)}"
                   f"{font(26)}{c('ink-muted')}{where}  ·  {esc(f.get('kind', ''))}  ·  {rate}"
                   f"${{alignr}}{font(28)}{state}")
        # Filling up is the point of a farm, so a full one is a to-do, not an alarm:
        # the bar stays blue and the pill carries the state.
        out.append(bar(frac, "series-1", px=16))
        out.append(f"{font(26)}{c('ink-muted')}{fnum(f.get('projected_items'))} / {fnum(f.get('capacity_items'))} items"
                   f"  ·  {_n(f.get('extractors', 0), 'extractor')}, {f.get('gas_extractors', 0)} gas,"
                   f" {_n(f.get('depots', 0), 'depot')}")
    return "\n".join(out)


def right_plants(d) -> str:
    """One row per kind of plant: what it gives, how many are planted and ready,
    how much of the harvest is already in stock, and when the rest is due."""
    if d.get("crafting_mode"):
        return refinery_output(d)
    bases = list((d.get("plants") or {}).values())
    items = d.get("items") or {}
    total = sum(b.get("total") or 0 for b in bases)
    mature = sum(b.get("mature") or 0 for b in bases)
    out = [header("Plants", f"{c('ink-muted')}{mature} of {total} ready  ·  projected")]
    if not bases:
        out.append(empty("nothing planted"))
        return "\n".join(out)
    for b in bases:
        kinds: dict[str, dict] = {}
        for p in b.get("plants") or []:
            k = kinds.setdefault(p.get("plant", "?"), {"n": 0, "ready": 0, "waits": [],
                                                       "yield_id": p.get("yield_id"), "yields": p.get("yields")})
            k["n"] += 1
            w = p.get("ready_in_seconds")
            if _ok(w) and w > 0:
                k["waits"].append(w)
            else:
                k["ready"] += 1
        rows = []
        order = sorted(kinds.items(), key=lambda kv: (-kv[1]["ready"], min(kv[1]["waits"]) if kv[1]["waits"] else 0, kv[0]))
        for plant, k in order:
            have = (items.get(k["yield_id"]) or {}).get("total") if k["yield_id"] else None
            nxt = fdur(min(k["waits"])) if k["waits"] else "--"
            if k["ready"] == k["n"]:
                state = pill("good", "harvest")
            elif k["ready"]:
                part = pill("good", f"{k['ready']} ready", 26)
                state = f"{part}{c('ink-2')}  ·  rest in {nxt}"
            else:
                state = f"{c('ink-2')}in {nxt}"
            rows.append([esc(plant), esc(k.get("yields") or "--"), fnum(k["n"]), f"{k['ready']} / {k['n']}",
                         fnum(have) if have is not None else "--", state])
        if len(bases) > 1:
            out.append(f"${{voffset 4}}{font(32, bold=True)}{c('ink-1')}{esc(b.get('base', '?'))}")
        out.append(table(["Plant", "Gives", "Planted", "Ready", "In stock", "State"], rows,
                         [MARGIN, MARGIN + 460, MARGIN + 880, MARGIN + 1060, MARGIN + 1280, MARGIN + 1560], {2, 3, 4}))
    return "\n".join(out)


def right_crafting(d, show: int = 6) -> str:
    """Known blueprints that stock cannot cover yet, grouped by the ingredient in
    the way, so the screen says what one trip or harvest would unlock."""
    cr = d.get("crafting") or {}
    groups = cr.get("by_ingredient") or []
    blocked = cr.get("blocked") or []
    out = [header("Almost craftable", f"{c('ink-muted')}{len(blocked)} known blueprints short of stock"
                                       if cr.get("computed_at") else "")]
    if not cr.get("computed_at"):
        out.append(empty("crafting not evaluated yet - a few seconds after the exporter reads a save"))
        return "\n".join(out)
    if not groups:
        out.append(empty("every known blueprint can be made from stock"))
        return "\n".join(out)
    for g in groups[:show]:
        its = g.get("items") or []
        shorts = [i.get("short") or 0 for i in its] or [0]
        alone = sum(1 for i in its if i.get("only"))
        span = fnum(min(shorts)) + (f" to {fnum(max(shorts))}" if max(shorts) != min(shorts) else "")
        out.append(f"${{voffset 4}}{font(34, bold=True)}{c('ink-1')}{esc(g.get('ingredient', '?'))}"
                   f"{font(26)}{c('ink-muted')}  ·  have {fnum(g.get('have'))}  ·  short by {span}"
                   f"${{alignr}}{font(28)}{c('ink-2')}{_n(len(its), 'blueprint')}  ·  {alone} need only this")
        names = ", ".join(f"{i.get('item', '?')} {fnum(i.get('short'))}" for i in its[:6])
        if len(its) > 6:
            names += f", +{len(its) - 6} more"
        out.append(f"{font(26)}{c('ink-2')}{esc(names)}")
    return "\n".join(out)


def right_tidy(d, show: int = 6) -> str:
    """Storage against data/nms_storage_plan.json: per destination container, the
    stacks that belong there but sit elsewhere, and whether it has the slots."""
    td = d.get("tidy") or {}
    moves = td.get("moves") or []
    conts = td.get("containers") or []
    out = [header("Tidy storage", f"{c('ink-muted')}{_n(len(moves), 'stack')} to move  ·  "
                                  f"{fnum(td.get('merges'))} to merge  ·  per the storage plan" if td.get("enabled") else "")]
    if not td.get("enabled"):
        out.append(note(f"no storage plan: {td.get('error', 'data/nms_storage_plan.json missing')}"))
        return "\n".join(out)
    if not moves and not td.get("merges"):
        out.append(f"{pill('good', 'everything is where the plan puts it')}")
        return "\n".join(out)
    by_to: dict[str, list] = {}
    for m in moves:
        by_to.setdefault(m["to"], []).append(m)
    shown = 0
    for cnt in conts:
        ms = by_to.get(cnt["container"])
        if not ms and not cnt.get("merges"):
            continue
        if shown >= show:
            break
        shown += 1
        over = cnt.get("over_capacity") or 0
        slots = (pill("serious", f"{cnt['stacks_after']} of {cnt['capacity']} slots - {over} too many", 24) if over
                 else f"{c('ink-2')}{cnt['stacks_after']} of {cnt['capacity']} slots after")
        tail = f"  ·  {_n(cnt['merges'], 'stack')} to merge" if cnt.get("merges") else ""
        out.append(f"${{voffset 4}}{font(32, bold=True)}{c('ink-1')}{esc(cnt['container'])}"
                   f"{font(26)}{c('ink-muted')}  ·  {esc(cnt.get('label', ''))}  ·  {_n(len(ms or []), 'stack')} in{tail}"
                   f"${{alignr}}{font(26)}{slots}")
        if ms:
            # several stacks of one item from one container read as one entry
            grouped: dict[tuple, list] = {}
            for m in ms:
                grouped.setdefault((m["item"], m["from"]), []).append(m["amount"])
            parts = []
            for (item, frm), amts in sorted(grouped.items(), key=lambda kv: -sum(kv[1])):
                n = f" ({len(amts)} stacks)" if len(amts) > 1 else ""
                parts.append(f"{item} {fnum(sum(amts))} from {frm}{n}")
            shown_parts, used = [], 0
            for part in parts:
                if used + len(part) + 2 > 160 or len(shown_parts) == 5:
                    break
                shown_parts.append(part)
                used += len(part) + 2
            text = ", ".join(shown_parts)
            if len(parts) > len(shown_parts):
                text += f", +{len(parts) - len(shown_parts)} more"
            out.append(f"{font(26)}{c('ink-2')}{esc(text)}")
    left = len(by_to) - shown
    if left > 0:
        out.append(empty(f"+ {left} more containers with stacks to take in"))
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
    where: dict[str, dict[str, int]] = {}
    for loc in d.get("locations") or []:
        per = where.setdefault(loc.get("id"), {})
        per[loc.get("location", "?")] = per.get(loc.get("location", "?"), 0) + (loc.get("amount") or 0)
    # A blueprint whose name matches: every ingredient, how much is held, and where.
    recipes = sorted(((k, v) for k, v in (d.get("blueprints") or {}).items() if q in (v.get("item") or "").lower()),
                     key=lambda kv: (len(kv[1].get("item") or ""), kv[1].get("item")))
    out = [header(f"Inventory  ·  “{query}”",
                  f"{c('ink-muted')}{len(items)} found  ·  {len(recipes)} blueprints  ·  right-click to clear")]
    totals = d.get("items") or {}
    for key, bp in recipes[:2]:
        makes = f"makes {bp['yield']}" if (bp.get("yield") or 1) > 1 else "makes 1"
        out.append(f"${{voffset 6}}{font(34, bold=True)}{c('ink-1')}Craft {esc(bp.get('item', key))}"
                   f"{font(26)}{c('ink-muted')}  ·  {makes}")
        for ing in bp.get("ingredients") or []:
            have = (totals.get(ing["id"]) or {}).get("total") or 0
            need = ing.get("amount") or 0
            ok = have >= need
            places = sorted(where.get(ing["id"], {}).items(), key=lambda kv: -kv[1])
            at = ", ".join(f"{p} {fnum(n)}" for p, n in places[:4]) if places else "none anywhere"
            state = pill("good", "ok", 24) if ok else pill("warning", f"short {fnum(need - have)}", 24)
            out.append(f"{font(28)}{c('ink-1')}{esc(ing.get('item', ing['id']))}{font(26)}{c('ink-2')}  x{fnum(need)}"
                       f"  ·  have {fnum(have)}  {state}{c('ink-muted')}  ·  {esc(at)}")
    if not items:
        if not recipes:
            out.append(empty(f"nothing in the inventory matches “{query}”"))
        return "\n".join(out)
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


def _stage_of(r: dict) -> str:
    """Against the stages the tables name when there are several (what the mission panel lists),
    else the game's internal steps, which run finer than the named stages."""
    st, cur = r.get("stages") or [], r.get("stage")
    if len(st) > 1 and _ok(cur):
        return f"stage {cur + 1} of {len(st)}"
    prog, final = r.get("progress"), r.get("final")
    return f"step {fnum(prog + 1)} of {fnum(final)}" if _ok(prog) and _ok(final) else ""


def _class(r: dict) -> str:
    return re.sub(r"(?<=[a-z])(?=[A-Z])", " ", r.get("class") or "")    # ChainedSecondary -> Chained Secondary


def _clip(s: str, n: int) -> str:
    s = str(s or "")
    return s if len(s) <= n else s[:n - 1] + "…"


def _where_words(wp: dict | None, short: bool = False) -> str:
    """A waypoint (/json missions.in_progress[].waypoint) in words: the planet and system, how far
    from where the save (or the game, live) has the player, what the game marked there."""
    if not wp:
        return ""
    live = wp.get("live") or {}
    if wp.get("address") is None:                     # the Anomaly's markers go wherever it is
        return wp.get("building") or ""
    place = wp.get("planet_name") or (f"planet {wp['planet']}" if wp.get("planet") else "in space")
    if short:
        if wp.get("here_planet"):
            far = "this planet"
        elif wp.get("here_system"):
            far = f"{place} · this system"
        else:
            far = f"{place} · {wp.get('system_name') or 'another system'}"
        return far + (f" · {fkm(live['dist'])}" if _ok(live.get("dist")) else "")
    bits = [place if wp.get("planet") else "", wp.get("system_name") or ""]
    far = wp.get("where") or "another system"
    if wp.get("distance_ly") is not None and not wp.get("here_system"):
        far += f", {fnum(wp['distance_ly'])} ly" if wp["distance_ly"] else ", same region"
    if _ok(live.get("dist")):
        far += f", {fkm(live['dist'])} away now"
    what = wp.get("settlement") or wp.get("building") or ""
    return "  ·  ".join(b for b in [" · ".join(x for x in bits if x), far, what] if b)


def right_mission(d) -> str:
    """The focus mission (/json missions.focus): the game's selected one unless the phone
    picked another. Every stage the tables list, done ones dimmed and the current one
    marked, then what finishing it hands out and where it leads."""
    m = d.get("missions") or {}
    rows = m.get("in_progress") or []
    r = next((x for x in rows if x.get("id") == m.get("focus")), None)
    if not r:
        out = [header("Mission", f"{c('ink-muted')}nothing to follow")]
        out.append(empty("no mission tables in data/nms_tables.json - run scripts/nms-extract-tables.py"
                         if not m.get("tables") else "no missions in progress - pick one up in the game"))
        return "\n".join(out)
    src = "chosen on the phone" if m.get("focus_source") == "phone" else "following the game's selection"
    out = [header("Mission", f"{c('ink-muted')}{esc(src)}")]
    tag = f"  {pill('idle', 'selected in game', 26)}" if r.get("selected") and m.get("focus_source") == "phone" else ""
    out.append(f"${{voffset 4}}{font(52, bold=True)}{c('ink-1')}{esc(_clip(r.get('title', '?'), 60))}"
               f"{font(30)}{c('ink-muted')}  {esc(_class(r))}{tag}"
               f"${{alignr}}{font(30, mono=True)}{c('ink-2')}{_stage_of(r)}")
    prog, final = r.get("progress"), r.get("final")
    if _ok(prog) and _ok(final) and final:
        out.append(bar(prog / final, "series-1", px=14))
    wp = r.get("waypoint")
    if wp:
        out.append(f"${{voffset 2}}{font(26)}{c('ink-muted')}Where  {font(30)}{c('ink-1')}{esc(_clip(_where_words(wp), 120))}")
    stages, cur = r.get("stages") or [], r.get("stage")
    if not stages:
        out.append(f"{font(32)}{c('ink-1')}{esc(r.get('objective') or 'in progress')}")
    for i, (_, text) in enumerate(stages):
        if cur is not None and i < cur:          # done: dimmed and ticked
            out.append(f"{c('good')}{glyph('✔', 28)} {font(28)}{c('ink-muted')}{esc(_clip(text, 130))}")
        elif i == cur:                           # now: the brightest line on the panel
            out.append(f"${{voffset 2}}{c('series-1')}{glyph('▶', 34)} {font(36, bold=True)}{c('ink-1')}"
                       f"{esc(_clip(text, 100))}{font(26)}{c('series-1')}  now")
        else:                                    # still ahead
            out.append(f"{c('ink-muted')}{glyph('○', 28)} {font(28)}{c('ink-2')}{esc(_clip(text, 130))}")
    if r.get("rewards"):
        out.append(f"${{voffset 6}}{font(26)}{c('ink-muted')}Rewards  {font(28)}{c('ink-2')}"
                   f"{esc(_clip(', '.join(r['rewards']), 130))}")
    nxt = r.get("leads_to_titles") or r.get("leads_to") or []
    if nxt:
        nxt = list(dict.fromkeys(nxt))           # seeded follow-ups repeat a title
        out.append(f"{font(26)}{c('ink-muted')}Leads to  {font(28)}{c('ink-2')}{esc(_clip(', '.join(nxt), 130))}")
    return "\n".join(out)


NEED_VERB = {"collect": "collect", "have": "have", "use": "use / hand over", "craft": "craft", "build": "build",
             "know": "learn", "install": "install", "repair": "repair"}


def right_mission_needs(d, show: int = 10) -> str:
    """The items the focus mission's current and later stages wait for: have against the
    amount, where it is, and short / ok / can craft. Nothing at all when it needs none,
    so the slot takes no room (right_slot)."""
    m = d.get("missions") or {}
    r = next((x for x in (m.get("in_progress") or []) if x.get("id") == m.get("focus")), None)
    needs = (r or {}).get("needs") or []
    if not needs:
        return ""
    out = [header("Mission needs", f"{c('ink-muted')}current stage first, later ones dimmed")]
    stages = r.get("stages") or []
    any_ok = {}                                  # per stage: one of an any-of set is enough
    for n in needs:
        if n.get("any"):
            any_ok[n["progress"]] = any_ok.get(n["progress"], False) or bool(n.get("ok"))
    last = None
    for n in needs[:show]:
        p = n.get("progress")
        if p != last:
            title = next((t for num, t in reversed(stages) if num is not None and num <= p), None)
            lead = "now" if n.get("current") else "later"
            any_word = "  ·  any one of" if any(x.get("any") for x in needs if x.get("progress") == p) else ""
            out.append(f"${{voffset 4}}{font(24)}{c('series-1' if n.get('current') else 'ink-muted')}{lead}"
                       f"{c('ink-muted')}  {esc(_clip(title or '', 80))}{any_word}")
            last = p
        cur = n.get("current")
        ink, ink2 = ("ink-1", "ink-2") if cur else ("ink-muted", "ink-muted")
        amt = n.get("amount")
        verb = NEED_VERB.get(n.get("kind"), n.get("kind") or "")
        qty = f"{fnum(amt)} " if _ok(amt) and n.get("kind") not in ("know", "install", "repair", "build") else ""
        have = n.get("have") or 0
        if n.get("kind") in ("know", "install", "repair"):
            got = {"know": "known", "install": "installed", "repair": "working"}[n["kind"]] if have else "--"
        elif n.get("kind") == "build":
            got = f"{fnum(have)} placed"
        else:
            got = f"have {fnum(have)}"
        where = _where(d, n.get("id"), 1) if n.get("kind") not in ("know", "install", "repair", "build") and have else ""
        if n.get("ok") or (n.get("any") and any_ok.get(p)):
            tone, word = "good", "ok"
        elif _ok(n.get("can_make")) and n["can_make"] > 0:
            tone, word = "warning", f"can craft {fnum(n['can_make'])}"
        elif n.get("kind") in ("know", "install", "repair", "build"):
            tone, word = "serious", "not yet"
        elif _ok(n.get("short")):
            tone, word = "serious", f"short {fnum(n['short'])}"
        else:
            tone, word = "serious", "needed"           # no amount: the game decides how many
        st = pill(tone if cur else "idle", word, 24)
        out.append(f"{font(30 if cur else 26)}{c(ink)}{esc(verb)} {qty}{esc(_clip(n.get('item'), 46))}"
                   f"${{goto {MARGIN + 1100}}}{font(26, mono=True)}{c(ink2)}{esc(got)}"
                   f"${{goto {MARGIN + 1380}}}{font(24)}{c('ink-muted')}{esc(_clip(where, 26))}"
                   f"${{alignr}}{font(24)}{st}")
    if len(needs) > show:
        out.append(empty(f"+ {len(needs) - show} more"))
    return "\n".join(out)


def right_missions(d, show: int = 8) -> str:
    """The other missions in progress, one line each, closest to done first
    (the exporter sorts them that way)."""
    m = d.get("missions") or {}
    rows = [r for r in (m.get("in_progress") or []) if not r.get("focus")]
    k = m.get("counts") or {}
    rep = f"  ·  {fnum(k['repeatable'])} repeatable, listed on the phone" if k.get("repeatable") else ""
    out = [header("Also in progress", f"{c('ink-muted')}{fnum(k.get('in_progress'))} in progress  ·  "
                                      f"{fnum(k.get('complete'))} done{rep}  ·  closest to done first")]
    if not rows:
        out.append(empty("nothing else in progress"))
        return "\n".join(out)
    for r in rows[:show]:
        tag = f"{c('ink-muted')}{glyph('●', 22)} " if r.get("selected") else ""
        wt = _where_words(r.get("waypoint"), short=True)
        out.append(f"{tag}{font(30)}{c('ink-1')}{esc(_clip(r.get('title', '?'), 40))}"
                   f"{font(26)}{c('ink-2')}  ·  {esc(_clip(r.get('objective') or 'in progress', 70 if wt else 90))}"
                   + (f"{font(24)}{c('ink-muted')}  ·  {esc(_clip(wt, 40))}" if wt else "")
                   + f"${{alignr}}{font(26, mono=True)}{c('ink-muted')}{_stage_of(r)}")
    if len(rows) > show:
        out.append(empty(f"+ {len(rows) - show} more"))
    return "\n".join(out)


def right_inventory(d, show: int | None = None) -> str:
    query = _search()
    if query:
        return right_search(d, query)
    if show is None:
        show = 32 if (d.get("activity") or "idle") == "idle" else 16   # first on the screen when idle: room for more
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
             "fleet": left_fleet, "missions": left_missions, "tech": left_tech, "collection": left_collections,
             "lifetime": left_lifetime},
    "right": {"summary": right_summary, "planner": right_planner, "refiners": right_refiners, "farms": right_farms,
              "plants": right_plants, "crafting": right_crafting, "tidy": right_tidy, "inventory": right_inventory,
              "mission": right_mission, "mission_needs": right_mission_needs, "missions": right_missions},
}
SUBTITLE = {"left": "traveller", "right": "bases"}

# The right screen's panels per activity (set from the phone, /json activity), top to bottom;
# right.conf draws slot1..slotN and a slot past the end of the list is blank. Not gathering
# or crafting, the inventory comes first; gathering puts the farms and plants up top; crafting
# is the refinery board (the refiners/farms/plants sections draw the board, stock and output);
# mission is the focus mission's stages and the rest in progress, the bases' panels hidden.
LAYOUT = {
    "idle": ["summary", "inventory", "planner", "refiners", "plants", "farms"],
    "gathering": ["summary", "farms", "plants", "inventory"],
    "crafting": ["summary", "planner", "refiners", "farms", "plants", "inventory"],
    "mission": ["summary", "mission", "mission_needs", "missions", "inventory"],
}
SLOTS = max(len(v) for v in LAYOUT.values())
COLLAPSE = {"mission_needs"}


def right_slot(d, n: int) -> str:
    panels = LAYOUT.get(d.get("activity") or ("crafting" if d.get("crafting_mode") else "idle"), LAYOUT["idle"])
    # a panel with nothing to say (mission_needs) drops out, so the ones below move up into its slot
    panels = [p for p in panels if p not in COLLAPSE or SECTIONS["right"][p](d)]
    if n > len(panels):
        return ""
    out = SECTIONS["right"][panels[n - 1]](d)
    return out if n == 1 else "${voffset 24}" + out     # the gap above, only when the slot draws


def main(argv: list[str]) -> int:
    if len(argv) != 3 or argv[1] not in SECTIONS:
        print("usage: nms_conky.py left|right <section>", file=sys.stderr)
        return 2
    screen, section = argv[1], argv[2]
    try:
        d, err, age = load()
        if section == "head":
            act = (d.get("activity") or ("crafting" if d.get("crafting_mode") else "idle")) if d else "idle"
            sub = {"crafting": "refinery", "gathering": "gathering", "mission": "mission"}.get(act, SUBTITLE[screen]) if screen == "right" else SUBTITLE[screen]
            out = masthead(d, err, age, sub)
        elif d is None:
            out = ""                     # the masthead already says why
        elif screen == "right" and section.startswith("slot") and section[4:].isdigit():
            out = right_slot(d, int(section[4:]))
        else:
            out = SECTIONS[screen][section](d)
    except Exception as e:               # noqa: BLE001 - a bug shows, it doesn't blank
        out = note(f"{section}: {type(e).__name__}: {e}", "critical")
    sys.stdout.write(unscale(out) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
