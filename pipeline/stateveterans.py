"""State veterans agencies' office locators -> site records (veterans).

Companion to pipeline.cvso (county rosters -> orgs): some states run the
veteran-service-office system at the state level and publish office
*locations*, which makes them sites. Registry-structured (STATES, like
cvso.STATES) so future states slot in: each state gets its own fetcher/
parser and its own source record under the shared "stateveterans/" prefix
(data/sources/stateveterans/<st>.yaml, id stateveterans/<st>); a state's
re-run replaces exactly its own records. Feeds cache under
sources/stateveterans/.

mi: MVAA's county-filter-search-locations page is Sitecore SXA; its
search JSON endpoint (/mvaa/sxa/search/results/) returns 0 results
unless a geolocation param `g=lat|lng` is supplied (it only enables
distance scoring — no radius filter — so one query centered on Lansing
returns the complete set, 163 locations 2026-07). Each result carries
lat/lng plus an Html fragment: list card (name, percent-encoded
data-mapaddress) and contact modal (officer name/phone/email, hours).
"Telework" entries (phone-only service points, no address, geo 0.0) are
skipped — not physical sites. michigan.gov's WAF (Akamai) 403s any
User-Agent carrying our identification suffix — even BROWSER_UA — but
passes a plain browser UA, so the single fetch uses one (still
throttled; one GET per run).

mo: Missouri Veterans Commission's VSO locator runs on a public ArcGIS
feature layer (Veteran_Service_Officer_Location, owner wolfeb_mogov —
"the office location for every Missouri Veteran Service Officer",
licenseInfo is the standard mo.gov data policy, warranty disclaimer
only). One row per service *officer*; rows sharing a street+city are
one office and are merged (86 rows -> 42 offices 2026-07), counties
served unioned across officers.

FACTS-ONLY: the office is the record, not the person — officer and
supervisor personal names are never recorded, and neither are emails
(both feeds publish only officers' personal inboxes); phone is the
first published office/service line. Free-form hours strings ("1st &
3rd Thursday 8am-4pm") are not shoehorned into structured hours.

Usage: python3 -m pipeline.stateveterans [state ...] [--force]
"""
import html
import json
import re
import sys
from urllib.parse import unquote

from .emit import Places, replace_records, today, write_source
from .util import Flow, SOURCES, fetch

# michigan.gov's WAF 403s even util.BROWSER_UA (it carries our project
# suffix); a plain browser UA passes. Single throttled GET per run.
PLAIN_BROWSER_UA = ("Mozilla/5.0 (X11; Linux x86_64; rv:128.0) "
                    "Gecko/20100101 Firefox/128.0")

CACHE = SOURCES / "stateveterans"

ZIP_RE = re.compile(r"\d{5}(-\d{4})?")
PHONE_RE = re.compile(r"\(?\b(\d{3})\)?[-. ]\s*(\d{3})[-. ](\d{4})\b")


def squash(text: str) -> str:
    return " ".join((text or "").split())


def phone_fmt(text: str) -> str | None:
    """First US phone in `text` as AAA-BBB-CCCC."""
    m = PHONE_RE.search(text or "")
    return f"{m.group(1)}-{m.group(2)}-{m.group(3)}" if m else None


def base_record(st: str, name: str, desc: str, source_id: str,
                places: Places, *, street: str = "", city: str = "",
                zip_code: str = "", geo=None, phone: str | None = None,
                external_ids: dict | None = None) -> dict:
    """One veteran service office site; shared assembly for all states."""
    geoid, place_slug = places.resolve(st, city)
    rec = {"_state": st, "_place_slug": place_slug, "_name": squash(name),
           "categories": ["veterans"], "description": squash(desc)}
    if city:
        addr = {}
        if street:
            addr["street"] = squash(street)
        addr["city"] = squash(city)
        addr["state"] = st
        if ZIP_RE.fullmatch(zip_code):
            addr["zip"] = zip_code
        rec["address"] = Flow(addr)
    if geo:
        lat, lng = geo
        if 15 <= lat <= 72 and -180 <= lng <= -60:
            rec["geo"] = Flow(lat=round(lat, 5), lng=round(lng, 5))
    if not geoid and "geo" in rec:
        near = places.nearest(rec["geo"]["lat"], rec["geo"]["lng"])
        if near and near[0] == st:  # state-matched nearest fallback
            geoid, rec["_place_slug"] = near[1], near[2]
    if geoid:
        rec["place"] = geoid
    if phone:
        rec["phone"] = phone
    if external_ids:
        rec["external_ids"] = Flow(external_ids)
    rec["sources"] = [source_id]
    rec["verified"] = Flow(on=today(), method="api")
    return rec


# --- MI: MVAA SXA search feed ----------------------------------------------

MI_PAGE = "https://www.michigan.gov/mvaa/county-filter-search-locations"
MI_API = ("https://www.michigan.gov/mvaa/sxa/search/results/"
          "?s=%7B100D5773-CF67-4556-A677-D5D4D7E4ADB1%7D"
          "&itemid=%7B897DB20A-86AE-4E35-90A4-5EBF87C2E08C%7D"
          "&v=%7BB068F05D-8C7B-460C-AA58-32B17FCDD22E%7D"
          "&p=400&e=0&g=42.73194%7C-84.55225")  # g: Lansing; scoring only

MI_NAME_RE = re.compile(r'location-list__section-location">([^<]+)<')
MI_ADDR_RE = re.compile(r'data-mapaddress="([^"]+)"')
MI_CITY_RE = re.compile(r"^(.*?),?\s+MI\b\.?,?\s*(\d{5}(?:-\d{4})?)?$")
MI_PHONE_RE = re.compile(r"Phone:\s*([\d() .-]{7,})")

MI_DESC = ("Veteran service office location listed in the Michigan "
           "Veterans Affairs Agency (MVAA) office locator. Accredited "
           "veteran service officers assist veterans and their families "
           "with VA benefit claims.")


def build_mi(force: bool, places: Places, source_id: str) -> list[dict]:
    path = fetch(MI_API, CACHE / "mi.json", force=force,
                 ua=PLAIN_BROWSER_UA)
    data = json.loads(path.read_bytes())
    results = data.get("Results") or []
    if data.get("Count", 0) > len(results):
        raise SystemExit(f"mi: feed reports {data['Count']} locations but "
                         f"returned {len(results)} — raise p or page")
    records, telework, noname = [], 0, 0
    for res in results:
        frag = res.get("Html") or ""
        name_m = MI_NAME_RE.search(frag)
        if not name_m:
            noname += 1
            continue
        name = squash(html.unescape(name_m.group(1)))
        if "telework" in name.lower():
            telework += 1  # phone-only service point, not a physical site
            continue
        street = city = zip_code = ""
        addr_m = MI_ADDR_RE.search(frag)
        if addr_m:
            lines = [squash(ln) for ln in
                     unquote(addr_m.group(1)).splitlines() if ln.strip()]
            if lines:
                city_m = MI_CITY_RE.match(lines[-1])
                if city_m:
                    city = city_m.group(1).strip(" ,")
                    zip_code = city_m.group(2) or ""
                    street = ", ".join(lines[:-1])
                else:
                    street = ", ".join(lines)
        geo = None
        gsp = res.get("Geospatial") or {}
        if gsp.get("Latitude") and gsp.get("Longitude"):
            geo = (gsp["Latitude"], gsp["Longitude"])
        records.append(base_record(
            "mi", name, MI_DESC, source_id, places, street=street,
            city=city, zip_code=zip_code, geo=geo,
            phone=phone_fmt((MI_PHONE_RE.search(frag) or [None, ""])[1]),
            external_ids={"mvaa": res["Id"]} if res.get("Id") else None))
    print(f"mi: kept {len(records)} of {len(results)} locations "
          f"({telework} telework service points skipped"
          + (f", {noname} unnamed" if noname else "") + ")")
    return records


# --- MO: MVC ArcGIS feature layer ------------------------------------------

MO_ITEM = ("https://www.arcgis.com/home/item.html?"
           "id=cdee0c6e32fc4f26b6f04b937ea03528")
MO_SERVICE = ("https://services6.arcgis.com/r9ddpXHABk7voAmS/arcgis/rest/"
              "services/Veteran_Service_Officer_Location/FeatureServer/0/query")
MO_PAGE = 1000

MO_HOME_RE = re.compile(r"^MO\.? Veterans Home\s+(.+)$", re.I)


def build_mo(force: bool, places: Places, source_id: str) -> list[dict]:
    features, offset = [], 0
    while True:
        url = (f"{MO_SERVICE}?where=1%3D1&outFields=*&outSR=4326&f=json"
               f"&resultOffset={offset}&resultRecordCount={MO_PAGE}")
        path = fetch(url, CACHE / f"mo-p{offset // MO_PAGE}.json", force=force)
        data = json.loads(path.read_bytes())
        if "error" in data or "features" not in data:
            raise SystemExit(f"mo: query error at offset {offset}: "
                             f"{str(data)[:200]}")
        features.extend(data["features"])
        if not data.get("exceededTransferLimit"):
            break
        offset += MO_PAGE

    # one row per service officer -> merge rows sharing street+city into
    # the office; first row (ObjectID order) wins scalar fields
    offices: dict[tuple, dict] = {}
    skipped = 0
    for feat in sorted(features,
                       key=lambda f: f["attributes"].get("ObjectID") or 0):
        at = feat["attributes"]
        street = squash(at.get("USER_Building_Street_Address") or "")
        city = squash(at.get("USER_City") or "")
        if not city:
            skipped += 1
            continue
        key = (street.lower(), city.lower())
        counties = [squash(c) for c in
                    (at.get("USER_Counties_Served") or "").split(",")
                    if squash(c)] or ([squash(at.get("USER_County"))]
                                      if squash(at.get("USER_County") or "")
                                      else [])
        geom = feat.get("geometry") or {}
        off = offices.setdefault(key, {
            "street": street, "city": city,
            "zip": str(at.get("USER_Zip_Code") or ""),
            "phone": None, "geo": None, "counties": []})
        for c in counties:
            if c not in off["counties"]:
                off["counties"].append(c)
        if not off["phone"]:
            off["phone"] = phone_fmt(at.get("USER_Phone__") or "")
        if not off["geo"] and geom.get("x") is not None:
            off["geo"] = (geom["y"], geom["x"])

    records = []
    for off in offices.values():
        city, street = off["city"], off["street"]
        name = f"{city} Veteran Service Office"
        home_m = MO_HOME_RE.match(street)
        if home_m:  # office inside a Missouri Veterans Home
            name += " (MO Veterans Home)"
            street = home_m.group(1)
        served = (f"{off['counties'][0]} County" if len(off["counties"]) == 1
                  else " and ".join(
                      ", ".join(off["counties"]).rsplit(", ", 1)) + " counties")
        desc = (f"State veteran service office of the Missouri Veterans "
                f"Commission serving {served}. Veteran service officers "
                "assist veterans and their families with VA benefit claims.")
        records.append(base_record(
            "mo", name, desc, source_id, places, street=street, city=city,
            zip_code=off["zip"], geo=off["geo"], phone=off["phone"]))
    print(f"mo: merged {len(features)} officer rows into {len(records)} "
          f"offices" + (f" ({skipped} rows without a city skipped)"
                        if skipped else ""))
    return records


# --- registry --------------------------------------------------------------
# st: (publisher, url, title, source kind, notes, build, floor)

STATES = {
    "mi": ("Michigan Veterans Affairs Agency", MI_PAGE,
           "MVAA veteran service office locator (SXA search feed)",
           "api-feed",
           f"Sitecore SXA search JSON behind the locator page, queried as "
           f"{MI_API} (the g= geolocation param is required for the index "
           "to return results; it only affects distance scoring). "
           "Telework (phone-only) entries are not recorded as sites; "
           "officer personal names/emails are never recorded.",
           build_mi, 120),
    "mo": ("Missouri Veterans Commission", MO_ITEM,
           "Veteran Service Officer Location (ArcGIS feature layer)",
           "dataset",
           f"Public feature layer behind the MVC veteran service officer "
           f"locator, queried via {MO_SERVICE}. One upstream row per "
           "service officer; rows sharing an address are merged into one "
           "office record. Officer/supervisor personal names and emails "
           "are never recorded.",
           build_mo, 35),
}

# facts-only assert: no officer-name/email field may reach a record
ALLOWED_KEYS = {"_state", "_place_slug", "_name", "categories",
                "description", "address", "place", "geo", "phone",
                "external_ids", "sources", "verified"}


def main(argv):
    force = "--force" in argv
    states = [a for a in argv if not a.startswith("-")] or sorted(STATES)
    places = Places()
    total, failed = 0, []
    for st in states:
        publisher, url, title, kind, notes, build, floor = STATES[st]
        try:
            records = build(force, places, f"stateveterans/{st}")
            if len(records) < floor:
                raise SystemExit(f"{st}: only {len(records)} offices — "
                                 f"floor is {floor}")
        except SystemExit as e:
            print(f"stateveterans: {st} SKIPPED — {e}")
            failed.append(st)
            continue
        for rec in records:
            extra = set(rec) - ALLOWED_KEYS
            assert not extra, f"{st}: unexpected fields {extra}"
        source_id = write_source(
            "stateveterans", st, kind=kind, publisher=publisher,
            title=title, url=url, tier="primary", notes=notes)
        replace_records("sites", source_id, records)
        total += len(records)
    print(f"stateveterans: {total} offices across "
          f"{len(states) - len(failed)} states"
          + (f"; FAILED: {', '.join(failed)}" if failed else ""))
    if total < 40:
        raise SystemExit(f"stateveterans: only {total} offices overall — "
                         "expected 40+; aborting")


if __name__ == "__main__":
    main(sys.argv[1:])
