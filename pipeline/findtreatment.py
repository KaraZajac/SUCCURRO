"""SAMHSA FindTreatment.gov locator -> site records (su-treatment / mh-treatment).

Bulk strategy: the developer guide's state-ID queries (limitType=1) return
empty/garbled results in practice, but a single national radius query
(limitType=2, 6,000 km from the CONUS centroid) returns the full facility set
(~24.5k records, 13 pages at pageSize=2000). Raw responses cached under
sources/samhsa/. Federal public domain.

Usage: python3 -m pipeline.findtreatment [--force]
"""
import json
import sys

from .emit import Places, replace_records, today, write_source
from .util import Flow, SOURCES, fetch

API = ("https://findtreatment.gov/locator/exportsAsJson/v2"
       "?sType=both&sAddr=%2239.8,-98.6%22&limitType=2&limitValue=6000000"
       "&pageSize=2000&page={page}")

TYPE_CATEGORIES = {
    "SA": ["su-treatment"],
    "MH": ["mh-treatment"],
    "BOTH": ["su-treatment", "mh-treatment"],
}


def categories_for(row):
    tf = (row.get("type_facility") or "").upper()
    if tf in TYPE_CATEGORIES:
        return TYPE_CATEGORIES[tf]
    for svc in row.get("services") or []:
        if svc.get("f2") == "TC":
            text = (svc.get("f3") or "").lower()
            cats = []
            if "substance use" in text:
                cats.append("su-treatment")
            if "mental health" in text:
                cats.append("mh-treatment")
            if cats:
                return cats
    return ["su-treatment", "mh-treatment"]


def fetch_all(force):
    rows, page, total_pages = [], 1, 1
    while page <= total_pages:
        cache = SOURCES / "samhsa" / "findtreatment" / f"national-p{page}.json"
        path = fetch(API.format(page=page), cache, force=force)
        data = json.loads(path.read_text())
        if "rows" not in data:
            raise SystemExit(f"findtreatment: unexpected payload on page {page}: {data}")
        total_pages = data.get("totalPages") or 1
        rows.extend(data["rows"])
        page += 1
    if len(rows) < 20000:
        raise SystemExit(f"findtreatment: only {len(rows)} rows — expected ~24k; aborting")
    return rows


def main(argv):
    force = "--force" in argv
    places = Places()
    source_id = write_source(
        "samhsa", "findtreatment",
        kind="dataset", publisher="SAMHSA (BHSIS)",
        title="FindTreatment.gov Treatment Facility Locator",
        url="https://findtreatment.gov/", tier="primary",
    )

    records, seen, skipped_state = [], {}, 0
    for row in fetch_all(force):
        name = " ".join(p for p in (row.get("name1"), row.get("name2")) if p).strip()
        city = (row.get("city") or "").strip()
        st = (row.get("state") or "").strip().lower()
        if not name:
            continue
        if st not in places.by_state:
            skipped_state += 1
            continue
        key = (name.lower(), (row.get("street1") or "").lower(), city.lower())
        if key in seen:
            # same facility listed under multiple types — union the categories
            prior = seen[key]
            for cat in categories_for(row):
                if cat not in prior["categories"]:
                    prior["categories"].append(cat)
            continue
        geoid, place_slug = places.resolve(st, city)
        rec = {
            "_state": st, "_place_slug": place_slug, "_name": name,
            "categories": categories_for(row),
            "address": Flow({k: v for k, v in {
                "street": row.get("street1"), "city": city,
                "state": st, "zip": (row.get("zip") or "")[:5] or None,
            }.items() if v}),
        }
        if geoid:
            rec["place"] = geoid
        try:
            rec["geo"] = Flow(lat=round(float(row["latitude"]), 5),
                              lng=round(float(row["longitude"]), 5))
        except (KeyError, TypeError, ValueError):
            pass
        if row.get("phone"):
            rec["phone"] = row["phone"]
        if row.get("website"):
            rec["website"] = row["website"]
        rec["sources"] = [source_id]
        rec["verified"] = Flow(on=today(), method="api")
        seen[key] = rec
        records.append(rec)
    if skipped_state:
        print(f"skipped {skipped_state} rows in states/territories outside the place registry")

    replace_records("sites", source_id, records)


if __name__ == "__main__":
    main(sys.argv[1:])
