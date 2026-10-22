"""Power budget of a base's extractors, from the save and the base-building table.

What the save gives: every generator, solar panel, biofuel generator, battery
and extractor, and each battery's charge (UserData >> 32; 45,000 = full, the
table's storage). What it does not: the class of the power hotspot under an
electromagnetic generator, whether a biofuel generator has fuel (no maintenance
record sits within 4.9 m of any of them), and which parts the wires join (the
saved wires stop short of generators; see farmcheck.py).

So the check is about extractors, whose 50 kP each is certain, against the
supply that is certain at night (electromagnetic generators at class C, 150 kP)
and the supply that might be there (class S, 300 kP; biofuel, 50 kP if fuelled).
Other powered parts (rooms, lights, teleporters) draw only when wired to the
grid, so they are reported as "up to", not added to the demand.

Standard library only.
"""
from __future__ import annotations

import math

EXTRACTORS = ("U_EXTRACTOR_S", "U_GASEXTRACTOR")
EM, SOLAR, BIO, BATTERY = "U_GENERATOR_S", "U_SOLAR_S", "U_BIOGENERATOR", "U_BATTERY_S"
# Power hotspot class strengths (REGIONHOTSPOTSTABLE); an electromagnetic
# generator makes rate_per_s (1) x strength kP.
DEFAULT_CLASSES = {"C": 150, "B": 220, "A": 250, "S": 300}


def _rate(buildings: dict, oid: str, default: float) -> float:
    b = buildings.get(oid) or {}
    if oid == BIO:      # Fuel network part that adds Power while it burns
        return next((d["rate"] for d in b.get("dependencies", []) if d.get("network") == "Power"), default)
    if oid in EXTRACTORS:
        return -next((d["rate"] for d in b.get("dependencies", []) if d.get("network") == "Power"), -default)
    return b.get("rate_per_s", default)


def base_power(base: dict, tables: dict) -> dict | None:
    """None for a base with no extractors and no power parts."""
    buildings = tables.get("buildings") or {}
    classes = ((tables.get("extraction") or {}).get("hotspots") or {}).get("Power", {}).get("class_strength") or DEFAULT_CLASSES
    count: dict = {}
    charge = 0
    other = 0.0
    for o in base.get("Objects") or []:
        oid = (o.get("ObjectID") or "").lstrip("^")
        count[oid] = count.get(oid, 0) + 1
        if oid == BATTERY:
            charge += (o.get("UserData") or 0) >> 32
        b = buildings.get(oid)
        if b and b.get("network") == "Power" and b.get("rate_per_s", 0) < 0:
            other -= b["rate_per_s"]
    ext = sum(count.get(e, 0) for e in EXTRACTORS)
    em, sol, bio, bat = (count.get(k, 0) for k in (EM, SOLAR, BIO, BATTERY))
    if not (ext or em or sol or bio or bat):
        return None

    demand = ext * _rate(buildings, "U_EXTRACTOR_S", 50)
    lo, hi = min(classes.values()), max(classes.values())
    em_lo, em_hi = em * _rate(buildings, EM, 1) * lo, em * _rate(buildings, EM, 1) * hi
    bio_kp = bio * _rate(buildings, BIO, 50)
    sol_kp = sol * _rate(buildings, SOLAR, 50)
    capacity = bat * ((buildings.get(BATTERY) or {}).get("storage") or 45000)

    out = {"extractors": ext, "demand_kp": demand, "other_up_to_kp": other,
           "em": em, "em_kp": [em_lo, em_hi], "solar": sol, "solar_kp": sol_kp, "bio": bio, "bio_kp": bio_kp,
           "batteries": bat, "charge": charge, "capacity": capacity,
           "charge_pct": round(100 * charge / capacity) if capacity else None}
    if demand and charge:
        out["battery_minutes"] = round(charge / demand / 60, 1)    # carrying every extractor alone

    if not demand:
        out.update(status="none", headline="No extractors")
    elif em_lo >= demand:
        out.update(status="good", headline="Covered day and night",
                   why=f"{em} electromagnetic generator{'s' if em != 1 else ''} give at least {em_lo:.0f} kP "
                       f"even on class C hotspots; extractors need {demand:.0f} kP (if they are wired together: "
                       f"the save cannot show that)")
    elif em_hi >= demand:
        need = next(c for c, s in sorted(classes.items(), key=lambda x: x[1]) if em * s >= demand)
        out.update(status="warning", headline=f"Needs class {need} or better power hotspots",
                   why=f"extractors need {demand:.0f} kP; {em} generators give {em_lo:.0f}-{em_hi:.0f} kP by hotspot "
                       f"class, which the save does not record"
                       + (f"; {bio} biofuel generators could make up {bio_kp:.0f} kP if fuelled" if bio else ""))
    elif em_hi + bio_kp >= demand:
        out.update(status="warning", headline="Nights depend on biofuel",
                   why=f"extractors need {demand:.0f} kP; at night only "
                       + (f"{em} generators ({em_lo:.0f}-{em_hi:.0f} kP) and " if em else "")
                       + f"{bio} biofuel generators ({bio_kp:.0f} kP if fuelled; fuel is not in the save) can supply it")
    else:
        short = demand - em_hi - bio_kp
        day = em_hi + bio_kp + sol_kp >= demand
        out.update(status="critical", headline=f"Short {short:.0f} kP at night",
                   why=f"extractors need {demand:.0f} kP; even class S generators and fuelled biofuel give "
                       f"{em_hi + bio_kp:.0f} kP" + ("; solar covers the day" if day else "; short in daytime too"))
    return out
