"""VA Facilities API (Lighthouse) -> site records (va-facility / vet-center).

Requires VA_API_KEY in .env (sandbox key works — the sandbox serves the real
facility dataset). Paginates the unfiltered v1 /facilities endpoint (the
documented /facilities/all bulk route 404s on sandbox). Cemeteries are
excluded — they aren't support services. CC0/public domain per data.gov.

Usage: python3 -m pipeline.va [--force]
"""
import json
import os
import re
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from . import _env
from .emit import Places, replace_records, today, write_source
from .util import Flow, SOURCES, UA

API = "https://sandbox-api.va.gov/services/va_facilities/v1/facilities?per_page=1000&page={page}"

TYPE_CATEGORIES = {
    "va_health_facility": ["va-facility", "health"],
    "vet_center": ["vet-center"],
    "va_benefits_facility": ["va-facility"],
}

DAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
DAY_TOKENS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
HOURS_RE = re.compile(r"^(\d{1,2})(\d{2})\s*(AM|PM)\s*-\s*(\d{1,2})(\d{2})\s*(AM|PM)$", re.I)


def fetch_page(key, page, cache, force):
    """Authenticated GET (util.fetch has no header support)."""
    if cache.exists() and not force:
        return cache
    req = Request(API.format(page=page),
                  headers={"User-Agent": UA, "apikey": key})
    try:
        with urlopen(req, timeout=120) as resp:
            body = resp.read()
    except (HTTPError, URLError, TimeoutError) as e:
        raise SystemExit(f"va: fetch failed page {page} ({e})")
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_bytes(body)
    time.sleep(1)
    return cache


def to_24h(hour, minute, ampm):
    hour = int(hour) % 12 + (12 if ampm.upper() == "PM" else 0)
    return f"{hour:02d}:{minute}"


def parse_hours(hours):
    """VA hours strings ('800AM-430PM', 'Closed', '24/7') -> hours entries,
    merging consecutive identical spans. Unparseable values are skipped."""
    spans: dict[tuple, list] = {}
    for day, token in zip(DAYS, DAY_TOKENS):
        m = HOURS_RE.match((hours.get(day) or "").strip())
        if not m:
            continue
        span = (to_24h(m[1], m[2], m[3]), to_24h(m[4], m[5], m[6]))
        spans.setdefault(span, []).append(token)
    return [Flow(days=days, open=o, close=c) for (o, c), days in spans.items()]


def main(argv):
    force = "--force" in argv
    _env.load()
    key = os.environ.get("VA_API_KEY")
    if not key:
        raise SystemExit("va: set VA_API_KEY in .env (free key: developer.va.gov)")
    places = Places()
    source_id = write_source(
        "va", "facilities-api",
        kind="api-feed", publisher="US Department of Veterans Affairs",
        title="VA Facilities API (Lighthouse)",
        url="https://developer.va.gov/explore/api/va-facilities", tier="primary",
    )

    facilities, page, total_pages = [], 1, 1
    while page <= total_pages:
        cache = SOURCES / "va" / f"facilities-p{page}.json"
        data = json.loads(fetch_page(key, page, cache, force).read_text())
        if "data" not in data:
            raise SystemExit(f"va: unexpected payload on page {page}: {str(data)[:200]}")
        total_pages = data["meta"]["pagination"]["totalPages"] if page == 1 else total_pages
        # totalPages reflects per_page from the request that produced it
        total_pages = data["meta"]["pagination"]["totalPages"]
        facilities.extend(data["data"])
        page += 1
    if len(facilities) < 2000:
        raise SystemExit(f"va: only {len(facilities)} facilities — expected ~2,500")

    records, skipped_type = [], 0
    for fac in facilities:
        a = fac.get("attributes") or {}
        cats = TYPE_CATEGORIES.get(a.get("facilityType"))
        if not cats:
            skipped_type += 1
            continue
        if ((a.get("operatingStatus") or {}).get("code") or "").upper() == "CLOSED":
            continue
        name = (a.get("name") or "").strip()
        addr = (a.get("address") or {}).get("physical") or {}
        state = (addr.get("state") or "").strip().lower()
        city = (addr.get("city") or "").strip()
        if not name or state not in places.by_state:
            continue
        geoid, place_slug = places.resolve(state, city)
        rec = {
            "_state": state, "_place_slug": place_slug, "_name": name,
            "categories": cats,
        }
        if a.get("classification"):
            rec["description"] = a["classification"]
        if city:
            street = ", ".join(p.strip() for p in
                               (addr.get("address1"), addr.get("address2"))
                               if p and p.strip())
            rec["address"] = Flow({k: v for k, v in {
                "street": street or None, "city": city, "state": state,
                "zip": (addr.get("zip") or "")[:5] or None,
            }.items() if v})
        if geoid:
            rec["place"] = geoid
        if isinstance(a.get("lat"), (int, float)) and a.get("lat"):
            rec["geo"] = Flow(lat=round(a["lat"], 5), lng=round(a["long"], 5))
        phone = ((a.get("phone") or {}).get("main") or "").strip()
        if phone:
            rec["phone"] = phone.split(" x")[0].split(" Ext")[0]
        if a.get("website"):
            rec["website"] = a["website"]
        hours = parse_hours(a.get("hours") or {})
        if hours:
            rec["hours"] = hours
        svc_names = [s["name"] for group in (a.get("services") or {}).values()
                     if isinstance(group, list)
                     for s in group if isinstance(s, dict) and s.get("name")]
        if svc_names:
            rec["services"] = sorted(set(svc_names))
        rec["external_ids"] = Flow(va=fac.get("id", ""))
        rec["sources"] = [source_id]
        rec["verified"] = Flow(on=today(), method="api")
        records.append(rec)
    print(f"skipped {skipped_type} non-service facilities (cemeteries etc.)")

    replace_records("sites", source_id, records)


if __name__ == "__main__":
    main(sys.argv[1:])
