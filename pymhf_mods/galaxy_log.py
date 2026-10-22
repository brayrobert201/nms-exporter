"""pyMHF mod: log star systems the game classifies, and galaxy / system map events.

Exploratory, like visor_log. The galaxy map classifies every system it draws;
cGcGalaxyAttributesAtAddress::Classify(lUA) fills mStar (cGcGalaxyStarAttributesData:
economy, wealth, conflict, race, star type, planet counts, planet seeds, flags),
all stored inline. Each universe address is logged once per session.

Hooks:
  cGcGalaxyAttributesAtAddress::Classify     systems, keyed by 64-bit universe address
  cGcGalaxyMap::Data::DoSolarPopup           the system the cursor is on (its UA)
  cGcNameGenerator::GenerateSolarSystemName  names with their seeds; paired with the last popup
  cGcNameGenerator::GeneratePlanetName       planet names with seeds (match PlanetSeeds)
  cGcFrontendPageSolarSystemMap::Update / OnMarkerPlaced   system map open/close, markers

Classify can run for thousands of systems per frame on the galaxy map, so its
hook returns at once for an address already logged. GeneratePlanetName runs
every frame for the current planet, so names are logged once per (seed, name).
Seen 2026-10-22: a system name's seed is the system's universe address, and a
planet name's seed is one of its system's PlanetSeeds. Output:
C:\\pymhf\\mod_saves\\live\\systems-YYYYMMDD.jsonl (one line per new system and per event).
"""
import json
import logging
import os
import time

from pymhf import Mod
from pymhf.gui.decorators import no_gui

import nmspy.data.types as nms
from nmspy.data.enums import (cGcAlienRace, cGcGalaxyStarAnomaly, cGcGalaxyStarTypes, cGcPlayerConflictData,
                              cGcTradingClass, cGcWealthClass)

logger = logging.getLogger("galaxy_log")

OUT_DIR = r"C:\pymhf\mod_saves\live"
MAP_IDLE_S = 0.75


def _name(v, enum):
    """Enum field as its name, or the raw number (see visor_log._name)."""
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


def _text(ptr):
    try:
        return str(ptr.contents).strip("\x00 ") or None
    except Exception:
        return None


def _address(ua: int) -> dict:
    """Universe address bits (nmspy cGcUniverseAddressData.to_UA, reversed)."""
    def signed(v, bits):
        return v - (1 << bits) if v >= 1 << (bits - 1) else v
    return {"voxel": [signed(ua & 0xFFF, 12), signed((ua >> 24) & 0xFF, 8), signed((ua >> 12) & 0xFFF, 12)],
            "system": (ua >> 40) & 0xFFF, "planet": (ua >> 52) & 0xF, "reality": (ua >> 32) & 0xFF}


@no_gui
class GalaxyLog(Mod):
    __author__ = "nms-exporter"
    __description__ = "Log classified star systems and galaxy/system map events to mod_saves/live/systems-*.jsonl"
    __version__ = "0.1"

    def __init__(self):
        super().__init__()
        os.makedirs(OUT_DIR, exist_ok=True)
        self._seen: set = set()
        self._popup = None           # (t, ua) of the last galaxy-map popup
        self._sysmap_seen = 0.0
        self._sysmap_open = False
        self._failed = set()
        self._names = set()
        logger.info("galaxy_log writing systems-*.jsonl")

    def _write(self, kind, **fields):
        if kind in ("planet_name", "system_name"):
            key = (kind, fields.get("seed"), fields.get("name"))
            if key in self._names:
                return
            self._names.add(key)
        now = time.time()
        day = time.strftime("%Y%m%d", time.localtime(now))
        with open(os.path.join(OUT_DIR, f"systems-{day}.jsonl"), "a") as f:
            f.write(json.dumps({"t": round(now, 2), "event": kind, **fields}) + "\n")

    def _guard(self, where, fn):
        # never raise into pyMHF (it would disable the hook); report each failing hook once
        try:
            fn()
        except Exception as e:
            if where not in self._failed:
                self._failed.add(where)
                logger.exception(f"{where} failed")
                self._write("error", where=where, error=repr(e))

    @nms.cGcGalaxyAttributesAtAddress.Classify.after
    def on_classify(self, this, lUA):
        ua = int(lUA)
        if ua in self._seen or not this:
            return
        self._seen.add(ua)
        self._guard("classify", lambda: self._system(this.contents, ua))

    def _system(self, attrs, ua):
        if not attrs.mbValid:
            return
        s = attrs.mStar
        n = int(s.NumberOfPlanets)
        self._write("system", ua=ua, ua_hex=f"0x{ua:X}", **_address(ua),
                    economy=_name(s.TradingData.TradingClass, cGcTradingClass),
                    wealth=_name(s.TradingData.WealthClass, cGcWealthClass),
                    conflict=_name(s.ConflictData, cGcPlayerConflictData),
                    race=_name(s.Race, cGcAlienRace), star=_name(s.Type, cGcGalaxyStarTypes),
                    anomaly=_name(s.Anomaly, cGcGalaxyStarAnomaly),
                    planets=n, prime_planets=int(s.NumberOfPrimePlanets), space_pois=int(s.NumberOfSpacePois),
                    planet_seeds=[int(x.Seed) & 0xFFFFFFFFFFFFFFFF for x in list(s.PlanetSeeds)[:max(0, min(n, 16))]],
                    abandoned=bool(s.AbandonedSystem), pirate=bool(s.IsPirateSystem),
                    gas_giant=bool(s.IsGasGiantSystem), giant=bool(s.IsGiantSystem), safe=bool(s.IsSystemSafe))

    @nms.cGcGalaxyMap.Data.DoSolarPopup.after
    def on_popup(self, this, lQueryResult):
        def go():
            ua = int(lQueryResult.contents.mu64UA)
            if not self._popup or self._popup[1] != ua:
                self._write("popup", ua=ua, ua_hex=f"0x{ua:X}")
            self._popup = (time.time(), ua)
        if lQueryResult:
            self._guard("popup", go)

    @nms.cGcNameGenerator.GenerateSolarSystemName.after
    def on_system_name(self, this, lu64Seed, lResult, lLocResult):
        def go():
            popup = self._popup if self._popup and time.time() - self._popup[0] < 1.0 else None
            self._write("system_name", seed=int(lu64Seed) & 0xFFFFFFFFFFFFFFFF, name=_text(lResult),
                        loc_name=_text(lLocResult), popup_ua=popup[1] if popup else None)
        self._guard("system_name", go)

    @nms.cGcNameGenerator.GeneratePlanetName.after
    def on_planet_name(self, this, lu64Seed, lResult, lLocResult):
        self._guard("planet_name", lambda: self._write(
            "planet_name", seed=int(lu64Seed) & 0xFFFFFFFFFFFFFFFF, name=_text(lResult), loc_name=_text(lLocResult)))

    @nms.cGcFrontendPageSolarSystemMap.Update.after
    def on_sysmap(self, this, lfTimeStep):
        self._sysmap_seen = time.time()
        if not self._sysmap_open:
            self._sysmap_open = True
            self._write("system_map_open")

    @nms.cGcFrontendPageSolarSystemMap.OnMarkerPlaced.after
    def on_sysmap_marker(self, this, lpMarker):
        self._write("system_map_marker")

    @nms.cGcPlayerEnvironment.Update.after
    def on_env(self, this, lfTimeStep):
        if self._sysmap_open and time.time() - self._sysmap_seen > MAP_IDLE_S:
            self._sysmap_open = False
            self._write("system_map_closed")
