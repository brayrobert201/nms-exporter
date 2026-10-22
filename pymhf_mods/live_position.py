"""pyMHF mod: write the player's position four times a second.

Runs inside NMS.exe (Windows Python in the game's Proton prefix). Installed by
`scripts/nms-hook`, which copies this directory to C:\\pymhf\\mods before
injecting.

Hook: cGcPlayerEnvironment::Update (every frame). Reads only the struct the
game passes in, plus the current galactic address when NMS.py has found the
application object (it may not have when attached mid-game; `ua` is then null).

Weather (0.2): cGcSky::SetStormState (fires on each storm transition, so a
storm already running when the mod loads shows up at its next change),
cGcSky::Update for the sun angle, and cGcPlanet::UpdateWeather for the current
planet's own data (weather type, storm frequency, intensity, hazard tables,
resources, life). Only values stored inside those structs are read; no pointer
is followed. Hazard tables are 6 floats each whose meaning is not documented.

Output, in C:\\pymhf\\mod_saves\\live (host: pfx/drive_c/pymhf/mod_saves/live):
  live.json          latest sample (with a "weather" block), replaced atomically every 0.25 s
  weather-YYYYMMDD.jsonl  one line per storm transition
  trail-YYYYMMDD.jsonl  one sample per line whenever the player moved > 2 m
                        or changed planet/location

`rel` is player position minus nearest planet centre: the frame the save uses
for base positions. `at` points behind the player (facing is -at). Both checked
in game: research/sources/measurements/2026-10-22-live-position-compass.md.
"""
import json
import logging
import os
import time

from pymhf import Mod
from pymhf.gui.decorators import no_gui

import nmspy.data.types as nms
from nmspy.common import gameData
from nmspy.data.enums import eStormState

logger = logging.getLogger("live_position")

OUT_DIR = r"C:\pymhf\mod_saves\live"
INTERVAL = 0.25
MIN_MOVE = 2.0
PLANET_INTERVAL = 5.0


def _vec(v):
    return [round(v.x, 3), round(v.y, 3), round(v.z, 3)]


def _name(v, enum=None):
    """Enum value (field or argument) as its name."""
    if hasattr(v, "name"):
        return v.name
    try:
        return enum(int(v)).name if enum else str(v)
    except (ValueError, TypeError):
        return str(v)


def _tkid(t):
    try:
        return bytes(t.value).split(b"\0")[0].decode(errors="replace").lstrip("^")
    except Exception:
        return None


def _planet_info(p):
    data = p.mPlanetData
    w, hz = data.Weather, data.Hazard
    return {
        "planet_index": p.miPlanetIndex,
        "weather": _name(w.WeatherType), "storm_frequency": _name(w.StormFrequency),
        "intensity": _name(w.WeatherIntensity),
        "hazard": {k: [round(x, 2) for x in getattr(hz, k)]
                   for k in ("Temperature", "Toxicity", "Radiation", "LifeSupportDrain", "SpookLevel")},
        "substances": [_tkid(data.CommonSubstanceID), _tkid(data.UncommonSubstanceID), _tkid(data.RareSubstanceID)],
        "life": _name(data.Life), "creature_life": _name(data.CreatureLife),
        "race": _name(data.InhabitingRace), "buildings": _name(data.BuildingLevel),
        # inline enums of cGcPlanetGenerationIntermediateData; the biome picks the Gas1 hotspot substance
        "biome": _name(data.GenerationData.Biome), "biome_subtype": _name(data.GenerationData.BiomeSubType),
        "planet_class": _name(data.GenerationData.Class), "size": _name(data.GenerationData.Size),
    }


def _address():
    state = gameData.player_state
    if state is None:
        return None
    ga = state.mLocation.GalacticAddress
    return {
        "reality": state.mLocation.RealityIndex,
        "voxel": [ga.VoxelX, ga.VoxelY, ga.VoxelZ],
        "system": ga.SolarSystemIndex,
        "planet": ga.PlanetIndex,
    }


@no_gui
class LivePosition(Mod):
    __author__ = "nms-exporter"
    __description__ = "Write the player's position to mod_saves/live four times a second"
    __version__ = "0.3"

    def __init__(self):
        super().__init__()
        os.makedirs(OUT_DIR, exist_ok=True)
        self._next = 0.0
        self._last = None
        self._failed_address = False
        self._storm = None          # {"state", "t"} from the last SetStormState
        self._sun = None            # cGcSky mfSolarSunAngle, raw
        self._sky_next = 0.0
        self._planet = None         # _planet_info of the nearest planet
        self._planet_next = 0.0
        self._env_planet = None
        self._planet_indices = set()
        logger.info(f"live_position writing to {OUT_DIR}")

    @nms.cGcPlayerEnvironment.Update.after
    def on_env_update(self, this, lfTimeStep):
        now = time.time()
        if now < self._next or not this:
            return
        self._next = now + INTERVAL
        env = this.contents
        self._env_planet = env.miNearestPlanetIndex
        pos = _vec(env.mPlayerTM.pos)
        planet = _vec(env.mNearestPlanetPos)
        sample = {
            "t": round(now, 1),
            "location": str(env.meLocation),
            "location_stable": str(env.meLocationStable),
            "planet_index": env.miNearestPlanetIndex,
            "distance_from_planet": round(env.mfDistanceFromPlanet, 1),
            "sealevel": round(env.mfNearestPlanetSealevel, 1),
            "in_atmosphere": bool(env.mbInsidePlanetAtmosphere),
            "pos": pos,
            "planet_pos": planet,
            "rel": [round(a - b, 3) for a, b in zip(pos, planet)],
            "at": _vec(env.mPlayerTM.at),
            "up": _vec(env.mUp),
            "ua": None,
        }
        if not self._failed_address:
            try:
                sample["ua"] = _address()
            except Exception:
                self._failed_address = True
                logger.exception("galactic address lookup failed; not trying again")

        tmp = os.path.join(OUT_DIR, "live.json.tmp")
        with open(tmp, "w") as f:
            json.dump({**sample, "weather": {"storm": self._storm, "sun_angle": self._sun, "planet": self._planet,
                                             "planet_indices_seen": sorted(self._planet_indices)}}, f)
        os.replace(tmp, os.path.join(OUT_DIR, "live.json"))

        if self._moved(sample):
            day = time.strftime("%Y%m%d", time.localtime(now))
            with open(os.path.join(OUT_DIR, f"trail-{day}.jsonl"), "a") as f:
                f.write(json.dumps(sample) + "\n")
            self._last = sample

    @nms.cGcSky.SetStormState.after
    def on_storm(self, this, leNewState):
        now = time.time()
        self._storm = {"state": _name(leNewState, eStormState), "t": round(now, 1)}
        day = time.strftime("%Y%m%d", time.localtime(now))
        with open(os.path.join(OUT_DIR, f"weather-{day}.jsonl"), "a") as f:
            f.write(json.dumps({**self._storm, "planet_index": self._env_planet}) + "\n")
        logger.info(f"storm state -> {self._storm['state']}")

    @nms.cGcSky.Update.after
    def on_sky(self, this, lfTimeStep):
        now = time.time()
        if now < self._sky_next or not this:
            return
        self._sky_next = now + 1.0
        self._sun = round(this.contents.mfSolarSunAngle, 4)

    @nms.cGcPlanet.UpdateWeather.after
    def on_planet_weather(self, this, lfTimeStep):
        # may run for every planet in the system; keep the nearest one, every few seconds
        if not this or time.time() < self._planet_next:
            return
        p = this.contents
        self._planet_indices.add(p.miPlanetIndex)
        if p.miPlanetIndex != self._env_planet:
            return
        self._planet_next = time.time() + PLANET_INTERVAL
        self._planet = _planet_info(p)

    def _moved(self, s):
        last = self._last
        if last is None:
            return True
        if (s["planet_index"], s["location"], s["ua"]) != (last["planet_index"], last["location"], last["ua"]):
            return True
        d2 = sum((a - b) ** 2 for a, b in zip(s["rel"], last["rel"]))
        return d2 > MIN_MOVE * MIN_MOVE
