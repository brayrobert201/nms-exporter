#!/usr/bin/env bash
# Merge the conky window rules into the user's kwinrulesrc and reload KWin.
# Run as the desktop user, inside the graphical session. Existing rules are
# kept; rules with the same names are replaced.
set -euo pipefail
cd "$(dirname "$0")/.."

RULES="$HOME/.config/kwinrulesrc"
SRC="kwin/nms-conky.kwinrule"

if [[ -f "$RULES" ]]; then
  cp "$RULES" "$RULES.bak-$(date +%F-%H%M%S)"
fi

python3 - "$RULES" "$SRC" <<'PY'
import configparser, os, sys
target, src = sys.argv[1], sys.argv[2]
cp = configparser.RawConfigParser()
cp.optionxform = str
if os.path.exists(target):
    cp.read(target)
new = configparser.RawConfigParser()
new.optionxform = str
new.read(src)
for sect in new.sections():
    if sect == "General":
        continue
    if cp.has_section(sect):
        cp.remove_section(sect)
    cp.add_section(sect)
    for k, v in new.items(sect):
        cp.set(sect, k, v)
rules = [s for s in cp.sections() if s != "General"]
if not cp.has_section("General"):
    cp.add_section("General")
cp.set("General", "count", str(len(rules)))
cp.set("General", "rules", ",".join(rules))
with open(target, "w") as fh:
    cp.write(fh, space_around_delimiters=False)
print(f"{len(rules)} rule(s) now in {target}")
PY

qdbus6 org.kde.KWin /KWin reconfigure 2>/dev/null \
  || qdbus org.kde.KWin /KWin reconfigure 2>/dev/null \
  || echo "Could not reload KWin over D-Bus - log out and back in."
