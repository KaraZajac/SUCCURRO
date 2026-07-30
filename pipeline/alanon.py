"""Al-Anon / Alateen meetings -> meeting records (recovery-meeting).

The WSO meeting search is powered by a Store Locator Widgets dataset — one
JSONP file holding every listed meeting worldwide (~14.5k). Not an offered
API, so this module is **permission-gated** (pipeline/_gate.py): it refuses to
write until Al-Anon answers our request or the DATA-RIGHTS fallback date is
reached, whichever comes first. `--dry-run` parses and reports without writing
and without consulting the gate, so the parser can be maintained meanwhile.

Widget custom fields have hashed keys that can change between dataset
versions, so field roles are detected by value shape (WSO id, day+time) rather
than by key. Meeting facts only: name, schedule, venue, language, access
notes — never member or contact information.

Usage: python3 -m pipeline.alanon [--force] [--dry-run]
"""
import json
import re
import sys
from collections import Counter

from . import _gate
from .emit import Places, replace_records, today, write_source
from .util import Flow, SOURCES, fetch

URL = "https://cdn.storelocatorwidgets.com/json/cba0758378166b88cf39e82d3f2d02af"

DAYS = {"sunday": "sun", "monday": "mon", "tuesday": "tue", "wednesday": "wed",
        "thursday": "thu", "friday": "fri", "saturday": "sat"}
SCHED_RE = re.compile(
    r"^(sunday|monday|tuesday|wednesday|thursday|friday|saturday)\s+"
    r"(\d{1,2}):(\d{2})\s*(am|pm)$", re.I)
WSO_RE = re.compile(r"^WSO ID\s*(\d+)", re.I)
# "306 3rd Street, Milan, IL, 61264, USA" — country last, zip before it
ADDR_RE = re.compile(
    r"^(?P<rest>.*?),\s*(?P<city>[^,]+),\s*(?P<state>[A-Z]{2}),\s*"
    r"(?P<zip>[\w ]+),\s*(?P<country>USA|United States)$", re.I)

LANGS = {"English": "en", "Español": "es", "Français": "fr"}
# filters that describe who the meeting serves / how it runs
TYPE_FILTERS = {
    "Families and Friends Only": "closed",
    "Families, Friends, and Observers Welcome": "open",
    "Beginners": "beginners", "Adult Children": "adult-children",
    "Women": "women", "Men": "men", "Parents": "parents",
    "Young Adults": "young-people", "LGBTQIA+": "lgbtq",
    "People of Color": "people-of-color", "Handicap Access": "wheelchair",
    "Child Care": "child-care", "Sign Language": "asl",
    "Fragrance Free": "fragrance-free",
}
ONLINE_RE = re.compile(r"\b(electronic|online|virtual|zoom)\b", re.I)
HYBRID_RE = re.compile(r"\bhybrid\b", re.I)


def parse_payload(text):
    """JSONP -> list of store dicts."""
    body = text[text.index("(") + 1: text.rindex(")")]
    data = json.loads(body)
    stores = data.get("stores") or []
    if len(stores) < 5000:
        raise SystemExit(f"alanon: only {len(stores)} stores — payload shape changed?")
    return stores


def field_roles(store):
    """Custom-field keys are hashed; find the schedule and WSO id by shape."""
    sched = wso = None
    for key, value in (store.get("data") or {}).items():
        if not isinstance(value, str):
            continue
        if sched is None and SCHED_RE.match(value.strip()):
            sched = value.strip()
        elif wso is None and WSO_RE.match(value.strip()):
            wso = WSO_RE.match(value.strip()).group(1)
    return sched, wso


def build(store, places, source_id):
    data = store.get("data") or {}
    name = (store.get("name") or "").strip()
    if not name:
        return None
    sched_text, wso = field_roles(store)
    if not sched_text:
        return None
    m = SCHED_RE.match(sched_text)
    day = DAYS[m.group(1).lower()]
    hour = int(m.group(2)) % 12 + (12 if m.group(4).lower() == "pm" else 0)
    entry = Flow(day=day, time=f"{hour:02d}:{m.group(3)}")

    filters = store.get("filters") or []
    fellowship = "alateen" if "Alateen" in filters else "al-anon"
    raw_addr = (data.get("address") or "").strip()
    am = ADDR_RE.match(raw_addr)
    if not am:
        return None                      # non-US or unparseable
    state = am.group("state").lower()
    if state not in places.by_state:
        return None
    city = am.group("city").strip()
    street = am.group("rest").strip(", ")

    blob = f"{raw_addr} {name} {data.get('description','')}"
    fmt = ("hybrid" if HYBRID_RE.search(blob)
           else "online" if ONLINE_RE.search(blob) else "in-person")

    rec = {
        "_state": state, "_place_slug": "online", "_name": name,
        "program": fellowship,
        "categories": ["recovery-meeting", "family-support"],
        "schedule": [entry],
        "format": fmt,
    }
    types = [TYPE_FILTERS[f] for f in filters if f in TYPE_FILTERS][:8]
    if types:
        rec["types"] = types
    langs = [LANGS[f] for f in filters if f in LANGS]
    if langs:
        rec["languages"] = langs

    if fmt != "online":
        geoid, place_slug = places.resolve(state, city)
        lat, lng = data.get("map_lat"), data.get("map_lng")
        geo = None
        if isinstance(lat, (int, float)) and isinstance(lng, (int, float)):
            if 17.5 <= lat <= 71.5 and -180 <= lng <= -64.5:
                geo = Flow(lat=round(lat, 5), lng=round(lng, 5))
        if not geoid and geo:
            near = places.nearest(geo["lat"], geo["lng"])
            if near and near[0] == state:
                _, geoid, place_slug = near
        rec["_place_slug"] = place_slug
        group = (data.get("description") or "").strip()
        if group and group.lower() != name.lower():
            rec["venue_name"] = group
        venue = {"city": city, "state": state}
        if street and not ONLINE_RE.search(street):
            venue["street"] = street
        zipc = (am.group("zip") or "").strip()
        if re.fullmatch(r"\d{5}", zipc):
            venue["zip"] = zipc
        rec["venue"] = Flow({k: v for k, v in venue.items() if v})
        if geoid:
            rec["place"] = geoid
        if geo:
            rec["geo"] = geo

    if wso:
        rec["external_ids"] = Flow(wso=wso)
    rec["sources"] = [source_id]
    rec["verified"] = Flow(on=today(), method="api")
    return rec


def main(argv):
    force = "--force" in argv
    dry = "--dry-run" in argv
    if not dry:
        basis = _gate.require("alanon")

    places = Places()
    cache = SOURCES / "alanon" / "meetings.js"
    stores = parse_payload(fetch(URL, cache, force=force).read_text(errors="replace"))

    source_id = "alanon/wso-meeting-locator"
    records, seen, stats = [], set(), Counter()
    for store in stores:
        rec = build(store, places, source_id)
        if rec is None:
            stats["skipped"] += 1
            continue
        key = (rec["external_ids"]["wso"] if rec.get("external_ids") else None,
               rec["_name"].lower(), rec["schedule"][0]["day"], rec["schedule"][0]["time"])
        if key in seen:
            stats["duplicate"] += 1
            continue
        seen.add(key)
        stats[rec["program"]] += 1
        stats[rec["format"]] += 1
        records.append(rec)

    print(f"alanon: {len(records)} US meetings from {len(stores)} listings "
          f"({dict(stats)})")
    if len(records) < 8000:
        raise SystemExit(f"alanon: only {len(records)} US meetings — expected ~10k")
    if dry:
        print("dry run — nothing written")
        return

    write_source(
        "alanon", "wso-meeting-locator",
        kind="api-feed", publisher="Al-Anon Family Group Headquarters (WSO)",
        title="Al-Anon and Alateen meeting locator dataset",
        url="https://al-anon.org/al-anon-meetings/find-an-al-anon-meeting/",
        tier="primary",
        notes=f"Facts-only re-expression of the published meeting locator. {basis}. "
              "Meeting facts only — no member or contact information. Removal on "
              "request, honored without argument.",
    )
    replace_records("meetings", source_id, records)


if __name__ == "__main__":
    main(sys.argv[1:])
