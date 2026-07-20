"""ACF Head Start locations (ArcGIS FeatureServer) -> site records (child-care).

Bulk strategy: ACF publishes every Head Start / Early Head Start service
location (~21k) on a public ArcGIS layer; paged queries (2000/page, ordered by
OBJECTID so pagination is stable) pull the full set. Rows with status "Closed"
are dropped; "Open" and "Not Reported" are kept — both are funded locations.
Raw pages cached under sources/acf/headstart/. Federal public domain.

Usage: python3 -m pipeline.headstart [--force]
"""
import json
import re
import sys

from .emit import Places, replace_records, today, write_source
from .util import Flow, SOURCES, fetch

PAGE_SIZE = 2000
API = ("https://services2.arcgis.com/ZQ4jTQn6k7VPXEwO/arcgis/rest/services/"
       "ACF_Head_Start_Locations/FeatureServer/0/query"
       "?where=1%3D1&outFields=*&orderByFields=OBJECTID&f=json"
       f"&resultRecordCount={PAGE_SIZE}&resultOffset={{offset}}")

_DIGITS = re.compile(r"\d")


def clean_phone(raw: str | None) -> str | None:
    """Normalize '(561) 261-6050' and friends to 10-digit dashed."""
    digits = "".join(_DIGITS.findall(raw or ""))
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    if len(digits) == 10:
        return f"{digits[:3]}-{digits[3:6]}-{digits[6:]}"
    return None


def fetch_all(force):
    rows, page = [], 1
    while True:
        cache = SOURCES / "acf" / "headstart" / f"locations-p{page}.json"
        path = fetch(API.format(offset=(page - 1) * PAGE_SIZE), cache, force=force)
        data = json.loads(path.read_text())
        if "features" not in data:
            raise SystemExit(f"headstart: unexpected payload on page {page}: {data}")
        rows.extend(f["attributes"] for f in data["features"])
        if len(data["features"]) < PAGE_SIZE:
            break
        page += 1
    if len(rows) < 15000:
        raise SystemExit(f"headstart: only {len(rows)} rows — expected ~21k; aborting")
    return rows


def main(argv):
    force = "--force" in argv
    places = Places()
    source_id = write_source(
        "acf", "head-start-locations",
        kind="dataset", publisher="ACF (Office of Head Start)",
        title="Head Start Center Locations",
        url="https://services2.arcgis.com/ZQ4jTQn6k7VPXEwO/arcgis/rest/services/"
            "ACF_Head_Start_Locations/FeatureServer/0",
        tier="primary",
    )

    records, seen = [], set()
    skipped_state = skipped_closed = 0
    for row in fetch_all(force):
        if (row.get("status") or "").strip() == "Closed":
            skipped_closed += 1
            continue
        name = (row.get("service_location_name") or "").strip()
        city = (row.get("city") or "").strip()
        st = (row.get("state") or "").strip().lower()
        if not name:
            continue
        if st not in places.by_state:
            skipped_state += 1
            continue
        street = (row.get("address_line_one") or "").strip()
        key = (name.lower(), street.lower(), city.lower())
        if key in seen:
            continue
        seen.add(key)
        zip5 = (row.get("zip") or "").strip()
        geoid, place_slug = places.resolve(st, city)
        rec = {
            "_state": st, "_place_slug": place_slug, "_name": name,
            "categories": ["child-care"],
            "address": Flow({k: v for k, v in {
                "street": street or None,
                "street2": (row.get("address_line_two") or "").strip() or None,
                "city": city, "state": st,
                "zip": zip5 if re.fullmatch(r"\d{5}", zip5) else None,
            }.items() if v}),
        }
        slots = row.get("funded_slots")
        desc = "Head Start early childhood program"
        if isinstance(slots, int) and slots > 0:
            desc += f" — {slots} funded slots"
        admin = (row.get("program_admin_name") or "").strip()
        if admin:
            desc += f"; operated by {admin}"
        rec["description"] = desc + "."
        if geoid:
            rec["place"] = geoid
        try:
            rec["geo"] = Flow(lat=round(float(row["latitude"]), 5),
                              lng=round(float(row["longitude"]), 5))
        except (KeyError, TypeError, ValueError):
            pass
        phone = clean_phone(row.get("service_location_phone_number")) \
            or clean_phone(row.get("registration_phone_number"))
        if phone:
            rec["phone"] = phone
        rec["sources"] = [source_id]
        rec["verified"] = Flow(on=today(), method="api")
        records.append(rec)

    if skipped_closed:
        print(f"skipped {skipped_closed} closed locations")
    if skipped_state:
        print(f"skipped {skipped_state} rows in states/territories outside the place registry")
    if len(records) < 15000:
        raise SystemExit(f"headstart: only {len(records)} site records after filtering; aborting")

    replace_records("sites", source_id, records)


if __name__ == "__main__":
    main(sys.argv[1:])
