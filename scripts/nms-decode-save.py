#!/usr/bin/env python3
"""Decode a No Man's Sky save (.hg) into readable JSON. Standard library only.

Usage:
  scripts/nms-decode-save.py SAVE.hg [OUT.json] [--mapping FILE] [--raw]

Default save dir (Steam/Proton):
  ~/.local/share/Steam/steamapps/compatdata/275850/pfx/drive_c/users/steamuser/AppData/Roaming/HelloGames/NMS/st_<steamid>/
  save.hg/save2.hg = slot 1 (auto/manual), save3.hg/save4.hg = slot 2, ...

The key mapping is data/nms_mapping.json in this repo; --mapping overrides it,
and a missing file is fetched from the MBINCompiler release.
"""
import argparse
import json
import os
import sys
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from nmsexporter import nmssave  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("save")
    ap.add_argument("out", nargs="?")
    ap.add_argument("--mapping", default=os.path.join(HERE, "..", "data", "nms_mapping.json"))
    ap.add_argument("--raw", action="store_true", help="keep obfuscated keys")
    a = ap.parse_args()
    mapping = None
    if not a.raw:
        if not os.path.exists(a.mapping):
            urllib.request.urlretrieve(nmssave.MAPPING_URL, a.mapping)
        mapping = nmssave.load_mapping(a.mapping)
    text = json.dumps(nmssave.decode_save(a.save, mapping), indent=1)
    if a.out:
        with open(a.out, "w") as fh:
            fh.write(text)
        print(f"wrote {a.out} ({len(text)} bytes)")
    else:
        sys.stdout.write(text)


if __name__ == "__main__":
    main()
