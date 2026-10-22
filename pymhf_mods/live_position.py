"""pyMHF mod: write the player's position about once a second.

Runs inside NMS.exe (Windows Python in the game's Proton prefix). Installed by
`scripts/nms-hook`, which copies this directory to C:\\pymhf\\mods before
injecting.

Hook: cGcPlayerEnvironment::Update (every frame). Reads only the struct the
game passes in, plus the current galactic address when NMS.py has found the
application object (it may not have when attached mid-game; `ua` is then null).

Output, in C:\\pymhf\\mod_saves\\live (host: pfx/drive_c/pymhf/mod_saves/live):
  live.json          latest sample, replaced atomically every second
  trail-YYYYMMDD.jsonl  one sample per line whenever the player moved > 2 m
                        or changed planet/location

`rel` is player position minus nearest planet centre, which should be the
frame the save uses for base positions (knowledge/mechanics/save-coordinates.md).
Unverified until compared against a base.
"""
import json
import logging
import os
import time

from pymhf import Mod
from pymhf.gui.decorators import no_gui

import nmspy.data.types as nms
from nmspy.common import gameData

logger = logging.getLogger("live_position")

OUT_DIR = r"C:\pymhf\mod_saves\live"
INTERVAL = 1.0
MIN_MOVE = 2.0


def _vec(v):
    return [round(v.x, 3), round(v.y, 3), round(v.z, 3)]


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
    __description__ = "Write the player's position to mod_saves/live once a second"
    __version__ = "0.1"

    def __init__(self):
        super().__init__()
        os.makedirs(OUT_DIR, exist_ok=True)
        self._next = 0.0
        self._last = None
        self._failed_address = False
        logger.info(f"live_position writing to {OUT_DIR}")

    @nms.cGcPlayerEnvironment.Update.after
    def on_env_update(self, this, lfTimeStep):
        now = time.time()
        if now < self._next or not this:
            return
        self._next = now + INTERVAL
        env = this.contents
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
            json.dump(sample, f)
        os.replace(tmp, os.path.join(OUT_DIR, "live.json"))

        if self._moved(sample):
            day = time.strftime("%Y%m%d", time.localtime(now))
            with open(os.path.join(OUT_DIR, f"trail-{day}.jsonl"), "a") as f:
                f.write(json.dumps(sample) + "\n")
            self._last = sample

    def _moved(self, s):
        last = self._last
        if last is None:
            return True
        if (s["planet_index"], s["location"], s["ua"]) != (last["planet_index"], last["location"], last["ua"]):
            return True
        d2 = sum((a - b) ** 2 for a, b in zip(s["rel"], last["rel"]))
        return d2 > MIN_MOVE * MIN_MOVE
