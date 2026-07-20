"""USDA FDPIR/CSFP administering agencies (ArcGIS) -> site records (food).

One FNS layer carries both programs (~162 rows): FDPIR — tribal organizations
distributing USDA foods on or near reservations — and CSFP — agencies running
monthly food packages for low-income seniors. The layer is point-only (no
address/phone) and the CSFP half is damaged upstream: the State column holds
the first 2-3 characters of multi-word state names ("NEW" / "YORK STATE
DEPARTMENT OF HEALTH"), and many points are plotted in the wrong state
entirely. States are reconstructed by re-joining the split name; coordinates
are kept only when the nearest registry place agrees with the record's state
(bad geo is worse than no geo). Federal public domain.

Usage: python3 -m pipeline.fdpir [--force]
"""
import json
import re
import sys

from .emit import Places, replace_records, today, write_source
from .util import Flow, SOURCES, fetch

LAYER = ("https://services1.arcgis.com/RLQu0rK7h4kbsBq5/arcgis/rest/services/"
         "FDPIR_CSFP_Adminstering_Agencies_v2/FeatureServer/0")  # sic: "Adminstering"

STATE_NAMES = {
    "ALABAMA": "al", "ALASKA": "ak", "ARIZONA": "az", "ARKANSAS": "ar",
    "CALIFORNIA": "ca", "COLORADO": "co", "CONNECTICUT": "ct", "DELAWARE": "de",
    "FLORIDA": "fl", "GEORGIA": "ga", "HAWAII": "hi", "IDAHO": "id",
    "ILLINOIS": "il", "INDIANA": "in", "IOWA": "ia", "KANSAS": "ks",
    "KENTUCKY": "ky", "LOUISIANA": "la", "MAINE": "me", "MARYLAND": "md",
    "MASSACHUSETTS": "ma", "MICHIGAN": "mi", "MINNESOTA": "mn",
    "MISSISSIPPI": "ms", "MISSOURI": "mo", "MONTANA": "mt", "NEBRASKA": "ne",
    "NEVADA": "nv", "NEW HAMPSHIRE": "nh", "NEW JERSEY": "nj",
    "NEW MEXICO": "nm", "NEW YORK": "ny", "NORTH CAROLINA": "nc",
    "NORTH DAKOTA": "nd", "OHIO": "oh", "OKLAHOMA": "ok", "OREGON": "or",
    "PENNSYLVANIA": "pa", "RHODE ISLAND": "ri", "SOUTH CAROLINA": "sc",
    "SOUTH DAKOTA": "sd", "TENNESSEE": "tn", "TEXAS": "tx", "UTAH": "ut",
    "VERMONT": "vt", "VIRGINIA": "va", "WASHINGTON": "wa",
    "WEST VIRGINIA": "wv", "WISCONSIN": "wi", "WYOMING": "wy",
    "DISTRICT OF COLUMBIA": "dc",
}
STATE_CODES = set(STATE_NAMES.values())
SMALL_WORDS = {"of", "and", "on", "for", "the", "in"}

DESCRIPTIONS = {
    "FDPIR": ("Food Distribution Program on Indian Reservations (FDPIR) "
              "administering agency — distributes USDA foods to income-eligible "
              "households living on or near participating reservations."),
    "CSFP": ("Commodity Supplemental Food Program (CSFP) administering agency — "
             "coordinates monthly USDA food packages for low-income adults 60 "
             "and older."),
}
CATEGORIES = {"FDPIR": ["food", "food-bank"], "CSFP": ["food", "seniors"]}


def titlecase(name: str) -> str:
    out = []
    for i, word in enumerate(name.split()):
        alpha = re.sub(r"[^A-Za-z]", "", word)
        if i and alpha.lower() in SMALL_WORDS:
            out.append(word.lower())
        elif len(alpha) == 2 and alpha.lower() in STATE_CODES:
            out.append(word.upper())
        else:
            out.append(word.capitalize())
    return " ".join(out)


def repair(raw_state: str, name: str) -> tuple[str | None, str]:
    """Return (state code or None, repaired name). The upstream CSFP export
    split multi-word state names into the State column ("NEW" | "YORK STATE
    DEPARTMENT OF HEALTH"); re-join and match against full state names."""
    raw = (raw_state or "").strip().rstrip(",")
    if raw.lower() in STATE_CODES:
        return raw.lower(), name
    joined = raw + name  # the split ate the boundary; concat restores letters
    compact = re.sub(r"[^A-Z]", "", joined.upper())
    for full, code in sorted(STATE_NAMES.items(), key=lambda kv: -len(kv[0])):
        squeezed = full.replace(" ", "")
        if compact.startswith(squeezed):
            rest = joined[len(squeezed):].strip()
            return code, (full.title() + " " + rest).strip()
    m = re.search(r",\s*([A-Za-z]{2})\s*$", joined)  # e.g. "CHOCTAW RESERVATION, MS"
    if m and m.group(1).lower() in STATE_CODES:
        return m.group(1).lower(), joined
    return None, name


def main(argv):
    force = "--force" in argv
    places = Places()
    source_id = write_source(
        "usda", "fdpir-csfp-agencies",
        kind="dataset", publisher="USDA Food and Nutrition Service",
        title="FDPIR/CSFP Administering Agencies", url=LAYER, tier="primary",
    )

    cache = SOURCES / "usda" / "fdpir-csfp.json"
    url = f"{LAYER}/query?where=1%3D1&outFields=*&outSR=4326&f=json&orderByFields=FID"
    data = json.loads(fetch(url, cache, force=force).read_text())
    if "features" not in data:
        raise SystemExit(f"fdpir: unexpected payload: {str(data)[:200]}")
    if data.get("exceededTransferLimit"):
        raise SystemExit("fdpir: layer grew past one page — add pagination")

    records, unresolved, geo_dropped = [], 0, 0
    for feat in data["features"]:
        a = feat["attributes"]
        program = (a.get("Program") or "").strip().upper()
        if program not in CATEGORIES:
            continue
        state, name = repair(a.get("State"), (a.get("Name") or "").strip())
        if not state or not name:
            unresolved += 1
            print(f"fdpir: unresolved state, skipping: {a.get('Name_State')!r}")
            continue
        rec = {
            "_state": state, "_place_slug": "unknown", "_name": titlecase(name),
            "categories": CATEGORIES[program],
            "description": DESCRIPTIONS[program],
        }
        geom = feat.get("geometry") or {}
        if isinstance(geom.get("y"), (int, float)):
            near = places.nearest(geom["y"], geom["x"])
            if near and near[0] == state:  # scrambled points plot out of state
                rec["place"], rec["_place_slug"] = near[1], near[2]
                rec["geo"] = Flow(lat=round(geom["y"], 5), lng=round(geom["x"], 5))
            else:
                geo_dropped += 1
        if a.get("Code") is not None:
            rec["external_ids"] = Flow(fns=str(a["Code"]))
        rec["sources"] = [source_id]
        rec["verified"] = Flow(on=today(), method="api")
        records.append(rec)

    if geo_dropped:
        print(f"dropped geo on {geo_dropped} rows plotted outside their state")
    if unresolved:
        print(f"skipped {unresolved} rows with unresolvable state")
    if len(records) < 120:
        raise SystemExit(f"fdpir: only {len(records)} records — expected ~162; aborting")

    replace_records("sites", source_id, records)


if __name__ == "__main__":
    main(sys.argv[1:])
