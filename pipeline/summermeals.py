"""USDA summer meal sites -> site records (meal-program). Seasonal.

The FNS ArcGIS org publishes a per-year layer (2026's is literally named
"...(Testing)" but is the live season feed behind fns.usda.gov/sfsp/sitefinder).
The layer name changes yearly, so we discover the newest Summer*<year> service
from the org's service list. Only OPEN sites (public, no enrollment) are kept;
leftover test rows are filtered. Federal public domain.

Usage: python3 -m pipeline.summermeals [--force]
"""
import json
import re
import sys
from urllib.parse import quote

from .emit import Places, replace_records, today, write_source
from .util import Flow, SOURCES, fetch

ORG = "https://services1.arcgis.com/RLQu0rK7h4kbsBq5/arcgis/rest/services"
YEAR_RE = re.compile(r"summer.*?(20\d\d)", re.I)
TEST_RE = re.compile(r"\btest\b|staggs", re.I)


def s(value):
    """Field cleaner: this feed uses the literal string 'null' for empty."""
    value = (value or "").strip()
    return "" if value.lower() == "null" else value


def newest_layer(force):
    services = json.loads(fetch(f"{ORG}?f=json", SOURCES / "usda" / "services.json",
                                force=True).read_text())["services"]
    best = None
    for svc in services:
        m = YEAR_RE.search(svc["name"])
        if m and (best is None or int(m.group(1)) > best[0]):
            best = (int(m.group(1)), svc["name"])
    if not best:
        raise SystemExit("summermeals: no Summer*<year> layer found on FNS ArcGIS org")
    return best


def main(argv):
    force = "--force" in argv
    places = Places()
    year, layer = newest_layer(force)
    print(f"using layer {layer} (season {year})")
    source_id = write_source(
        "usda", "summer-meal-sites",
        kind="dataset", publisher="USDA Food and Nutrition Service",
        title=f"Summer Meals Site Finder ({year} season)",
        url="https://www.fns.usda.gov/sfsp/sitefinder", tier="primary",
    )

    features, offset, page = [], 0, 1
    while True:
        cache = SOURCES / "usda" / f"summermeals-{year}-p{page}.json"
        url = (f"{ORG}/{quote(layer)}/FeatureServer/0/query?where=1%3D1&outFields=*"
               f"&f=json&orderByFields=MasterID&outSR=4326"
               f"&resultRecordCount=2000&resultOffset={offset}")
        data = json.loads(fetch(url, cache, force=force).read_text())
        if "features" not in data:
            raise SystemExit(f"summermeals: unexpected payload: {str(data)[:200]}")
        features.extend(data["features"])
        if not data.get("exceededTransferLimit") and len(data["features"]) < 2000:
            break
        offset += len(data["features"])
        page += 1

    records, seen, dropped = [], set(), 0
    for feat in features:
        a = feat["attributes"]
        name = s(a.get("Site_Name")).title()
        state = s(a.get("Site_State")).lower()
        city = s(a.get("Site_City")).title()
        if not name or state not in places.by_state:
            continue
        if s(a.get("Site_Type")).upper() != "OPEN":
            continue
        blob = " ".join(s(a.get(f)) for f in
                        ("Site_Name", "Site_Address1", "Site_Address2",
                         "Sponsoring_Organization"))
        if TEST_RE.search(blob):
            dropped += 1
            continue
        key = (name.lower(), s(a.get("Site_Address1")).lower(), city.lower())
        if key in seen:
            continue
        seen.add(key)
        geoid, place_slug = places.resolve(state, city)
        rec = {
            "_state": state, "_place_slug": place_slug, "_name": name,
            "categories": ["meal-program"],
        }
        if city:  # the address schema requires city; a few rows lack one
            rec["address"] = Flow({k: v for k, v in {
                "street": s(a.get("Site_Address1")).title() or None, "city": city,
                "state": state, "zip": s(a.get("Site_Zip"))[:5] or None,
            }.items() if v})
        sponsor = s(a.get("Sponsoring_Organization"))
        desc = f"Free summer meals for kids and teens ({year} season)"
        rec["description"] = f"{desc} — sponsored by {sponsor}." if sponsor else desc + "."
        if geoid:
            rec["place"] = geoid
        geom = feat.get("geometry") or {}
        if isinstance(geom.get("y"), (int, float)) and 15 < geom["y"] <= 72:
            rec["geo"] = Flow(lat=round(geom["y"], 5), lng=round(geom["x"], 5))
        phone = s(a.get("Site_Phone"))
        if phone:
            rec["phone"] = phone
        if s(a.get("MasterID")):
            rec["external_ids"] = Flow(usda_master=s(a.get("MasterID")))
        rec["sources"] = [source_id]
        rec["verified"] = Flow(on=today(), method="api")
        records.append(rec)
    if len(records) < 20000:
        raise SystemExit(f"summermeals: only {len(records)} open sites — layer changed?")
    if dropped:
        print(f"dropped {dropped} test rows")

    replace_records("sites", source_id, records)


if __name__ == "__main__":
    main(sys.argv[1:])
