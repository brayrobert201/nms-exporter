"""pyMHF mod: log what the analysis visor and the game's marker list do.

Exploratory: the aim is to find which game calls fire when the visor scans,
tags, or surveys (power / mineral / gas hotspots), and what they carry. Events
only, never per-frame data; each marker is logged when first seen and again
after MARKER_REPEAT_S.

Hooks (all matched NMS.exe 181442 in the offline signature scan):
  cGcBinoculars::UpdateTarget          per frame while the visor is up -> open/close events
  cGcBinoculars::UpdateScanBarProgress scan bar -> scan start / complete / abandon
  cGcBinoculars::PopulateDiscoveryInfo a scan result being filled in
  cGcBinoculars::SetMarker             the player tagging something
  cGcMarkerList::TryAddMarker / RemoveMarker  every marker the game places or clears
  cGcPlayerEnvironment::Update         (1 s) where the player is, for context
  cGcTextChatInput::ParseTextForCommands  chat commands (below)

Chat commands (typed in the game's text chat; the line is replaced by a reply):
  /hs S silver     what the visor says about the hotspot you stand on: class
                   and/or resource, either may be left out. The exporter
                   attaches it to the nearest hotspot within 50 m.
  /mark Ammonia field   a named point at your position, shown on the map
  /help            the list of these commands (also /hs or /mark on their own)

Reads only fields of the structs passed in; no pointer is followed. Marker
positions are logged raw (cTkPhysRelVec3 local + offset) and as local + offset
minus the nearest planet centre; that frame is unverified until a PlayerBase
marker is compared with the save's base position.

Output: C:\\pymhf\\mod_saves\\live\\visor-YYYYMMDD.jsonl
"""
import ctypes
import json
import logging
import math
import os
import time

from pymhf import Mod
from pymhf.gui.decorators import no_gui

import nmspy.data.types as nms
from nmspy.data.enums import cGcBuildingClassification, cGcMarkerType

logger = logging.getLogger("visor_log")

OUT_DIR = r"C:\pymhf\mod_saves\live"
MARKER_REPEAT_S = 60.0
VISOR_IDLE_S = 0.75         # no UpdateTarget for this long = visor closed
# High-churn marker types that say nothing about the visor or resources.
# Hotspot markers get their whole 0x2B0-byte struct logged as hex. Done its job:
# a class B and a class S marker differ only in position, label and type, so the
# class is not in the marker (2026-10-22). Kept for checking other fields.
RAW_TYPES = {"MineralHotspot", "GasHotspot", "PowerHotspot"}
MARKER_SIZE = 0x2B0
# The reply to /help, in the game's chat markup (<TITLE>...<> as nmspy's textChatManager uses).
HELP = ("<TITLE>Map commands<> (nms-exporter)\n"
        "<TITLE>/hs S silver<>  class and/or resource of the hotspot you stand on (either can be left out)\n"
        "<TITLE>/mark Ammonia field<>  a named flag at your position on the map\n"
        "<TITLE>/help<>  this list")
# SpacePoi moves every frame (879 of the first 902 lines, 2026-10-22).
QUIET_TYPES = {"NetworkPlayer", "NetworkPlayerShip", "NetworkPlayerVehicle", "NetworkPlayerFireTeam",
               "NetworkPlayerFireTeamShip", "NetworkPlayerFireTeamFreighter", "SpacePoi"}


def _v(v):
    return [round(v.x, 2), round(v.y, 2), round(v.z, 2)]


def _name(v, enum):
    """Enum field or argument as its name; the raw number if the enum has no
    such value (e.g. meBuildingClass read 63 on 2026-10-22). c_enum8 fields
    hold a one-byte bytes value, and their .name raises for unknown values."""
    try:
        raw = v if isinstance(v, int) else getattr(v, "value", v)
        if isinstance(raw, (bytes, bytearray)):
            raw = raw[0] if raw else 0
        raw = int(raw)
    except Exception:
        return str(v)
    try:
        return enum(raw).name
    except ValueError:
        return raw


def _text(s):
    try:
        return str(s).strip("\x00 ") or None
    except Exception:
        return None


@no_gui
class VisorLog(Mod):
    __author__ = "nms-exporter"
    __description__ = "Log analysis visor events and game markers to mod_saves/live/visor-*.jsonl"
    __version__ = "0.1"

    def __init__(self):
        super().__init__()
        os.makedirs(OUT_DIR, exist_ok=True)
        self._env_next = 0.0
        self._player = None          # {"pos", "planet_pos", "location", "heading_at"}
        self._visor_seen = 0.0
        self._visor_open = False
        self._scan = 0.0             # last scan-bar progress
        self._markers: dict = {}     # key -> next time it may be logged again
        logger.info("visor_log writing visor-*.jsonl")

    def _write(self, kind, **fields):
        now = time.time()
        row = {"t": round(now, 2), "event": kind, **fields}
        if self._player:
            row["player"] = self._player
        day = time.strftime("%Y%m%d", time.localtime(now))
        with open(os.path.join(OUT_DIR, f"visor-{day}.jsonl"), "a") as f:
            f.write(json.dumps(row) + "\n")

    # --- context, and closing the visor (UpdateTarget stops being called) ---
    @nms.cGcPlayerEnvironment.Update.after
    def on_env(self, this, lfTimeStep):
        now = time.time()
        if self._visor_open and now - self._visor_seen > VISOR_IDLE_S:
            self._visor_open = False
            self._write("visor_closed")
        if now < self._env_next or not this:
            return
        self._env_next = now + 1.0
        env = this.contents
        self._player = {"pos": _v(env.mPlayerTM.pos), "planet_pos": _v(env.mNearestPlanetPos),
                        "location": str(env.meLocation), "at": _v(env.mPlayerTM.at)}

    # --- the visor ---
    @nms.cGcBinoculars.UpdateTarget.after
    def on_visor(self, this, lfTimeStep):
        self._visor_seen = time.time()
        if not self._visor_open:
            self._visor_open = True
            self._write("visor_open")

    @nms.cGcBinoculars.UpdateScanBarProgress.after
    def on_scan_bar(self, this, lfScanProgress):
        p, last = float(lfScanProgress), self._scan
        if last <= 0.0 < p:
            self._write("scan_start")
        elif p >= 1.0 > last:
            self._write("scan_complete")
        elif p <= 0.0 < last < 1.0:
            self._write("scan_abandoned", reached=round(last, 2))
        self._scan = p

    @nms.cGcBinoculars.PopulateDiscoveryInfo.after
    def on_discovery(self, this, lDiscoveryInfo, lpTargetNode, lpTargetAttachment, lbSubmitDiscovery, lbSilent):
        self._write("discovery_info", submit=bool(lbSubmitDiscovery), silent=bool(lbSilent))

    @nms.cGcBinoculars.SetMarker.after
    def on_set_marker(self, this):
        self._write("visor_tag")

    # --- markers ---
    def _marker(self, kind, ptr):
        # never raise: pyMHF disables a detour that throws, and this one sees every marker
        try:
            self._marker_row(kind, ptr)
        except Exception as e:
            if not getattr(self, "_marker_failed", False):
                self._marker_failed = True
                logger.exception("marker read failed")
                self._write("marker_error", error=repr(e))

    def _marker_row(self, kind, ptr):
        if not ptr:
            return
        m = ptr.contents
        mtype = _name(m.meType, cGcMarkerType)
        if mtype in QUIET_TYPES:
            return
        local, offset = _v(m.mPosition.local), _v(m.mPosition.offset)
        key = (kind, mtype, tuple(round(a + b) for a, b in zip(local, offset)))
        now = time.time()
        if self._markers.get(key, 0.0) > now:
            return
        self._markers[key] = now + MARKER_REPEAT_S
        row = {"type": mtype, "building": _name(m.meBuildingClass, cGcBuildingClassification),
               "name": _text(m.mCustomName), "subtitle": _text(m.mCustomSubtitle),
               "local": local, "offset": offset}
        if mtype in RAW_TYPES:
            row["raw"] = ctypes.string_at(ctypes.addressof(m), MARKER_SIZE).hex()
        if self._player:
            w = [a + b for a, b in zip(local, offset)]
            row["rel"] = [round(a - b, 2) for a, b in zip(w, self._player["planet_pos"])]
            row["dist_from_player"] = round(math.dist(w, self._player["pos"]), 1)
        self._write(kind, **row)

    # --- chat commands ---
    @nms.cGcTextChatInput.ParseTextForCommands.before
    def on_chat(self, this, lMessageText):
        def go():
            msg = str(lMessageText.contents).strip()
            low = msg.lower()
            words = msg.split()
            if low in ("/help", "/hs", "/mark") or low.startswith("/help "):
                lMessageText.contents.set(HELP)        # usage, nothing recorded
                return
            if not (words and words[0].lower() in ("/hs", "/mark")):
                return
            p = self._player
            rel = [round(a - b, 2) for a, b in zip(p["pos"], p["planet_pos"])] if p else None
            if words[0].lower() == "/hs":
                words = words[1:]
                cls = next((w.upper() for w in words if w.upper() in ("C", "B", "A", "S")), None)
                res = " ".join(w for w in words if w.upper() not in ("C", "B", "A", "S")) or None
                self._write("label", rel=rel, **{"class": cls, "resource": res})
                reply = "Noted for the nearest hotspot: " + " ".join(x for x in (f"class {cls}" if cls else "", res or "") if x)
            else:
                name = msg[len("/mark"):].strip() or "mark"
                self._write("mark", name=name, rel=rel)
                reply = f"Marked {name!r} on the map"
            if rel is None:
                reply += " (position not known yet: try again in a second)"
            lMessageText.contents.set(reply)
        if lMessageText:
            try:
                go()
            except Exception as e:
                logger.exception("chat command failed")
                self._write("chat_error", error=repr(e))

    @nms.cGcMarkerList.TryAddMarker.before
    def on_add_marker(self, this, lPoint, lbUpdateTime):
        self._marker("marker_add", lPoint)

    @nms.cGcMarkerList.RemoveMarker.before
    def on_remove_marker(self, this, lExampleMarker):
        self._marker("marker_remove", lExampleMarker)
