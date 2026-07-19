"""HRSA Health Center Service Delivery and Look-Alike Sites -> site records.

Bulk strategy: data.hrsa.gov publishes a daily-refreshed CSV of every FQHC and
look-alike service delivery site (~19k rows, all Active) at a stable DD_Files
URL — no scraping of the download page needed. Raw file cached under
sources/hrsa/. Federal public domain.

Usage: python3 -m pipeline.hrsa [--force]
"""
import csv
import re
import sys

from .emit import Places, replace_records, today, write_source
from .util import Flow, SOURCES, fetch

CSV_URL = ("https://data.hrsa.gov/DataDownload/DD_Files/"
           "Health_Center_Service_Delivery_and_LookAlike_Sites.csv")

_DOMAIN = re.compile(r"^[A-Za-z0-9-]+(\.[A-Za-z0-9-]+)+(/|$)")
_PHONE = re.compile(r"^\d{3}-\d{3}-\d{4}")
_ZIP5 = re.compile(r"^\d{5}")


def clean_website(raw: str) -> str | None:
    """The column mixes bare domains, scheme'd URLs, and junk (N/A, none...)."""
    w = (raw or "").strip()
    m = re.match(r"^(https?)://(.+)", w, re.I)
    if m:
        return f"{m.group(1).lower()}://{m.group(2)}"
    if _DOMAIN.match(w):
        return f"https://{w}"
    return None


def load_rows(force):
    path = fetch(CSV_URL, SOURCES / "hrsa" / "health-center-sites.csv", force=force)
    with path.open(newline="", encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    if len(rows) < 10000:
        raise SystemExit(f"hrsa: only {len(rows)} rows — expected ~19k; aborting")
    return rows


def main(argv):
    force = "--force" in argv
    places = Places()
    source_id = write_source(
        "hrsa", "health-center-sites",
        kind="dataset", publisher="HRSA",
        title="Health Center Service Delivery and Look-Alike Sites",
        url=CSV_URL, tier="primary",
    )

    records, seen = [], set()
    skipped_state = skipped_status = 0
    for row in load_rows(force):
        if row.get("Site Status Description") != "Active":
            skipped_status += 1
            continue
        name = (row.get("Site Name") or "").strip()
        city = (row.get("Site City") or "").strip()
        st = (row.get("Site State Abbreviation") or "").strip().lower()
        if not name:
            continue
        if st not in places.by_state:
            skipped_state += 1
            continue
        street = (row.get("Site Address") or "").strip()
        key = (name.lower(), street.lower(), city.lower())
        if key in seen:
            continue
        seen.add(key)
        zip5 = _ZIP5.match((row.get("Site Postal Code") or "").strip())
        geoid, place_slug = places.resolve(st, city)
        rec = {
            "_state": st, "_place_slug": place_slug, "_name": name,
            "categories": ["community-health-center"],
            "address": Flow({k: v for k, v in {
                "street": street or None, "city": city,
                "state": st, "zip": zip5.group() if zip5 else None,
            }.items() if v}),
        }
        if geoid:
            rec["place"] = geoid
        try:
            rec["geo"] = Flow(
                lat=round(float(row["Geocoding Artifact Address Primary Y Coordinate"]), 5),
                lng=round(float(row["Geocoding Artifact Address Primary X Coordinate"]), 5))
        except (KeyError, TypeError, ValueError):
            pass
        phone = _PHONE.match((row.get("Site Telephone Number") or "").strip())
        if phone:
            rec["phone"] = phone.group()
        website = clean_website(row.get("Site Web Address"))
        if website:
            rec["website"] = website
        if row.get("BPHC Assigned Number"):
            rec["external_ids"] = Flow(bphc=row["BPHC Assigned Number"])
        rec["sources"] = [source_id]
        rec["verified"] = Flow(on=today(), method="api")
        records.append(rec)

    if skipped_status:
        print(f"skipped {skipped_status} non-active sites")
    if skipped_state:
        print(f"skipped {skipped_state} rows in states/territories outside the place registry")
    if len(records) < 10000:
        raise SystemExit(f"hrsa: only {len(records)} site records after filtering; aborting")

    replace_records("sites", source_id, records)


if __name__ == "__main__":
    main(sys.argv[1:])
