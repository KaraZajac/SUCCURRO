"""Salvation Army USA location finder -> site records (multi-category).

The national location-finder (salvationarmyusa.org/location-finder/, the page the
old gdosCenterSearch plugin redirects to) is a Zesty.io site whose search runs
entirely client-side over the CMS "instant" content API — no radius/grid sweep
needed. One unauthenticated GET per model returns the complete dataset: the
locations model (~3.4k items with name, street, lat/lng, phone, zip, GDOS id)
plus small lookup models (property types, states, cities, service types) that
location records reference by item zuid. Five requests total, cached under
sources/salvationarmy/.

Kept: corps community centers, service units/centers/extensions, shelters,
transitional housing, ARC/Harbor Light rehab centers, food pantries, DV centers,
Kroc centers, youth/senior/health/child-care sites — GDOS property types and
service tags mapped onto our taxonomy, upstream tag labels preserved in
services:. Skipped: thrift stores, donation drop boxes, warehouses, admin
offices, metro-area groupings, camps, correctional-service offices, and
worship/retail-only records (not help services).

Rights: no site-wide ToS exists (checked 2026-07; the only "legal" page in the
CMS is an Indiana-Division-scoped copyright notice covering page materials, not
facts); robots.txt allows all agents; the instant API is the same one their own
front end calls from every visitor's browser. Facts-only re-expression,
attributed.

Usage: python3 -m pipeline.salvationarmy [--force]
"""
import json
import re
import sys

from .emit import Places, replace_records, today, write_source
from .util import Flow, SOURCES, fetch

SITE = "https://www.salvationarmyusa.org"
CACHE = SOURCES / "salvationarmy"

# Zesty instant-API content models behind the location finder (zuids from the
# page's inline JS) and the minimum item count expected from each
MODELS = {
    "locations": ("6-b4c9aba69c-h2nqvm", 3000),
    "property-types": ("6-a8f0f4dfae-4tvz6n", 20),
    "states": ("6-ce888daf92-fpzvz1", 50),
    "cities": ("6-dcd5c9b192-tgsnht", 1500),
    "service-types": ("6-f0f2e8c49b-sdbvrb", 20),
}

# property types that are not help services
SKIP_TYPES = {
    "Thrift Store", "Donation Drop Box", "Warehouse", "Admin Office",
    "Metro Area", "Camp", "Correctional Service",
}

# property type -> taxonomy tokens
TYPE_CATEGORIES = {
    "Shelter": ["emergency-shelter"],
    "Transitional Housing Shelter": ["transitional-housing"],
    "Harbor Light Center": ["su-treatment"],
    "Adult Rehabilitation Center": ["su-treatment"],
    "Domestic Violence Center": ["domestic-violence"],
    "Food Pantry": ["food-pantry"],
    "Child Day Care Center": ["child-care"],
    "Senior Residence": ["seniors"],
    "Youth Program Center": ["family-youth"],
    "Health Service": ["health"],
}

# GDOS service tag -> taxonomy tokens; unmapped tags are kept verbatim in services:
SERVICE_CATEGORIES = {
    "Hunger": ["food-pantry"],
    "Community Meals": ["meal-program"],
    "Utility Rent Assistance": ["utility-assistance", "financial"],
    "Homelessness": ["emergency-shelter"],
    "Recovery": ["su-treatment"],
    "Domestic Violence": ["domestic-violence"],
    "Family Services": ["family-support"],
    "Family Counseling": ["counseling"],
    "Senior Services": ["seniors"],
    "Youth Services": ["family-youth"],
    "Health Services": ["health"],
}

# service tags that alone don't make a location a help service
NONSOCIAL = {
    "Worship and Spiritual Programs", "Thrift Stores", "Donation Dropoff",
    "Giving Back", "Holiday Giving",
}

ZIP_RE = re.compile(r"\d{5}(-\d{4})?")


def load_model(name: str, force: bool) -> list[dict]:
    zuid, floor = MODELS[name]
    path = fetch(f"{SITE}/-/instant/{zuid}.json", CACHE / f"{name}.json", force=force)
    data = json.loads(path.read_bytes()).get("data")
    if not isinstance(data, list) or len(data) < floor:
        raise SystemExit(f"salvationarmy: {name} model returned "
                         f"{len(data) if isinstance(data, list) else 'no'} items "
                         f"(expected >= {floor}) — API shape changed?")
    return data


def rel_zuids(content: dict, field: str) -> list[str]:
    v = content.get(field)
    if isinstance(v, dict) and v.get("data"):
        return [x["zuid"] for x in v["data"]]
    return []


def fix_case(name: str) -> str:
    name = name.strip()
    return name.title() if name.isupper() or name.islower() else name


def norm_phone(raw: str) -> str | None:
    digits = re.sub(r"\D", "", raw or "")
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    if len(digits) == 10:
        return f"{digits[:3]}-{digits[3:6]}-{digits[6:]}"
    return None


def main(argv):
    force = "--force" in argv
    places = Places()
    source_id = write_source(
        "salvationarmy", "location-finder",
        kind="api-feed", publisher="The Salvation Army USA",
        title="Salvation Army USA location finder (GDOS-backed content API)",
        url=f"{SITE}/location-finder/", tier="primary",
    )

    ptype_of = {r["meta"]["zuid"]: (r["content"].get("name") or r["meta"].get("title") or "").strip()
                for r in load_model("property-types", force)}
    state_of = {r["meta"]["zuid"]: (r["content"].get("state_code") or "").strip().lower()
                for r in load_model("states", force)}
    city_of = {r["meta"]["zuid"]: fix_case(r["meta"].get("name") or "")
               for r in load_model("cities", force)}
    svc_of = {r["meta"]["zuid"]: (r["meta"].get("title") or "").strip()
              for r in load_model("service-types", force)}

    records, seen = [], {}
    skipped_type = skipped_nonsocial = skipped_state = skipped_noname = merged = 0
    for item in load_model("locations", force):
        ct = item["content"]
        name = (ct.get("name") or "").strip()
        if not name:
            skipped_noname += 1
            continue

        ptypes = [ptype_of.get(z, "") for z in rel_zuids(ct, "property_type")]
        ptype = ptypes[0] if ptypes else ""
        if ptype in SKIP_TYPES:
            skipped_type += 1
            continue

        svc_titles = [t for t in (svc_of.get(z) for z in rel_zuids(ct, "services_offered")) if t]
        categories = list(TYPE_CATEGORIES.get(ptype, []))
        for t in svc_titles:
            for cat in SERVICE_CATEGORIES.get(t, []):
                if cat not in categories:
                    categories.append(cat)
        if not categories:
            if not ptype or (svc_titles and all(t in NONSOCIAL for t in svc_titles)):
                # untyped records are overwhelmingly thrift stores; typed corps
                # whose only tags are worship/retail aren't help services either
                skipped_nonsocial += 1
                continue
            # corps-family type (community center, service unit, ...) with no
            # informative tags: the property type itself asserts social services
            categories = ["family-support"]

        st = next((state_of.get(z, "") for z in rel_zuids(ct, "state")), "")
        if st not in places.by_state:
            skipped_state += 1
            continue
        city = next((city_of.get(z, "") for z in rel_zuids(ct, "city")), "")

        street = (ct.get("address") or "").strip()
        gdos = (ct.get("gdos_id") or "").strip()
        key = ("gdos", gdos) if gdos else (name.lower(), street.lower(), city.lower())
        if key in seen:
            prior = seen[key]
            for cat in categories:
                if cat not in prior["categories"]:
                    prior["categories"].append(cat)
            for t in svc_titles:
                if t not in prior.get("services", []):
                    prior.setdefault("services", []).append(t)
            merged += 1
            continue

        geoid, place_slug = places.resolve(st, city)
        rec = {
            "_state": st, "_place_slug": place_slug, "_name": name,
            "categories": categories,
        }
        if ptype:
            rec["description"] = f"Salvation Army {ptype.lower()}"
        addr = {}
        if street:
            addr["street"] = street
        if city:
            addr["city"] = city
            addr["state"] = st
            zip_code = str(ct.get("zipcode") or "").strip()
            if ZIP_RE.fullmatch(zip_code):
                addr["zip"] = zip_code
            rec["address"] = Flow(addr)
        try:
            lat, lng = float(ct["latitude"]), float(ct["longitude"])
            if 15 <= lat <= 72 and -180 <= lng <= -60:
                rec["geo"] = Flow(lat=round(lat, 5), lng=round(lng, 5))
        except (KeyError, TypeError, ValueError):
            pass
        if not geoid and "geo" in rec:
            near = places.nearest(rec["geo"]["lat"], rec["geo"]["lng"])
            if near and near[0] == st:  # state-matched nearest fallback
                geoid = near[1]
        if geoid:
            rec["place"] = geoid
        phone = norm_phone(ct.get("contact_number"))
        if phone:
            rec["phone"] = phone
        path_full = (ct.get("path_full") or "").strip()
        if path_full.startswith("/"):
            rec["website"] = SITE + path_full
        if svc_titles:
            rec["services"] = svc_titles
        if gdos:
            rec["external_ids"] = Flow(gdos=gdos)
        rec["sources"] = [source_id]
        rec["verified"] = Flow(on=today(), method="api")
        seen[key] = rec
        records.append(rec)

    print(f"kept {len(records)} locations "
          f"(skipped: {skipped_type} non-service property types, "
          f"{skipped_nonsocial} worship/retail-only, {skipped_state} outside "
          f"place registry, {skipped_noname} unnamed; merged {merged} duplicates)")
    if len(records) < 800:
        raise SystemExit(f"salvationarmy: only {len(records)} locations — "
                         "expected 800+; aborting")

    replace_records("sites", source_id, records)


if __name__ == "__main__":
    main(sys.argv[1:])
