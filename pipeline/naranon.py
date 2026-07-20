"""Nar-Anon family groups -> meeting records (recovery-meeting, family-support).

The Nar-Anon WSO group database is a Knack app whose public finder view is an
open API: GET api.knack.com/v1/scenes/scene_18/views/view_26/records (same
1,241 rows as scene_5/view_7 but with a few extra columns) with headers
X-Knack-Application-Id: 54dd0787f294e1891969b4db and X-Knack-REST-API-Key:
"knack". 100 rows/page, 13 pages worldwide. Field map (probed 2026-07):
field_2 group name, field_5 venue name, field_1_raw structured address with
lat/lng, field_3 group number, field_6 day (English or Spanish), field_82
time ("7:30pm"), field_182 timezone label, field_4 fellowship tags
(Nar-Anon / Nar-Anon Virtual / Narateen), field_93 languages, field_67
status, field_8/field_256 notes. The research note's scene_57 "virtual
meetings" table is an auth-gated test table ("Ahou tests", 401) — virtual
meetings are the "Nar-Anon Virtual" rows of the main table.

The endpoint is fragile, so every page is archived to sources/naranon/
before parsing (cache = archive; --force refetches). US filter: registry
state (code or full name) + in-US-bounds coordinates when present; online-
only rows almost never carry a US address and are skipped when stateless.

Usage: python3 -m pipeline.naranon [--force]
"""
import json
import re
import sys
import time as _time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .bmlt import in_us_bounds, norm_state
from .emit import Places, replace_records, today, write_source
from .util import Flow, ROOT, SOURCES, UA

API = ("https://api.knack.com/v1/scenes/scene_18/views/view_26/records"
       "?page={}&rows_per_page=100")
HEADERS = {
    "X-Knack-Application-Id": "54dd0787f294e1891969b4db",
    "X-Knack-REST-API-Key": "knack",
    "User-Agent": UA,
}

DAYS = {
    "sunday": "sun", "monday": "mon", "tuesday": "tue", "wednesday": "wed",
    "thursday": "thu", "friday": "fri", "saturday": "sat",
    # Spanish rows exist (South America, but also potentially PR)
    "domingo": "sun", "lunes": "mon", "martes": "tue", "miercoles": "wed",
    "jueves": "thu", "viernes": "fri", "sabado": "sat",
}
DAY_WORD_RE = re.compile(
    r"\b(sunday|monday|tuesday|wednesday|thursday|friday|saturday"
    r"|domingo|lunes|martes|miercoles|jueves|viernes|sabado)s?\b", re.I)
# "2nd and 4th Wednesday", "Every other Monday", "Last Monday of the Month"
DAY_QUALIFIER_RE = re.compile(r"\d(st|nd|rd|th)|every other|last|/month", re.I)
TIME_RE = re.compile(r"(\d{1,2})(?::(\d{2}))?\s*([ap])\.?m", re.I)
TIME_24H_RE = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)\b")
LANGS = {"english": "en", "spanish": "es", "french": "fr", "portuguese": "pt",
         "farsi": "fa", "persian": "fa", "russian": "ru", "italian": "it",
         "greek": "el", "hebrew": "he", "arabic": "ar", "german": "de"}
TAG_RE = re.compile(r"<[^>]+>")


def fetch_page(page: int, force: bool) -> dict:
    """Archive-then-parse: raw page JSON lands in sources/naranon/ first."""
    cache = SOURCES / "naranon" / f"page-{page:02d}.json"
    if not cache.exists() or force:
        cache.parent.mkdir(parents=True, exist_ok=True)
        _time.sleep(1.0)  # polite; Knack rate-limits aggressively
        req = Request(API.format(page), headers=HEADERS)
        try:
            with urlopen(req, timeout=120) as resp:
                cache.write_bytes(resp.read())
        except (HTTPError, URLError, TimeoutError) as e:
            raise SystemExit(f"naranon: fetch failed page {page} ({e})")
        print(f"fetched page {page} -> {cache.relative_to(ROOT)}")
    return json.loads(cache.read_text())


def parse_time(raw: str) -> str | None:
    m = TIME_RE.search(raw or "")
    if m:
        h = int(m[1]) % 12 + (12 if m[3].lower() == "p" else 0)
        return f"{h:02d}:{m[2] or '00'}"
    m = TIME_24H_RE.match((raw or "").strip())
    # bare 24h like "20:00" is unambiguous only in the evening
    if m and int(m[1]) >= 13:
        return f"{m[1]}:{m[2]}"
    return None


def parse_days(raw: str) -> list[str]:
    """'Wednesday & Thursday' / 'Thursdays' / 'Martes y Jueves' -> day tokens."""
    days = []
    for word in DAY_WORD_RE.findall(
            raw.replace("é", "e").replace("á", "a")):
        token = DAYS[word.lower()]
        if token not in days:
            days.append(token)
    return days


def strip_html(raw: str) -> str:
    return re.sub(r"\s+", " ", TAG_RE.sub(" ", raw or "")).strip()


def build_record(row: dict, places: Places, source_id: str):
    """One Knack row -> (record, None) or (None, why)."""
    if (row.get("field_67") or "").strip() != "Active":
        return None, "inactive"
    tags = " ".join(str(t) for t in (row.get("field_4_raw") or []))
    virtual = "Virtual" in tags
    in_person = bool(re.search(r"Nar-Anon(?!\s*Virtual)|Narateen", tags))

    addr = row.get("field_1_raw") if isinstance(row.get("field_1_raw"), dict) else {}
    state_raw = re.sub(r"^washington,? d\.?c\.?$", "district of columbia",
                       (addr.get("state") or "").strip(), flags=re.I)
    st = norm_state(state_raw, places.by_state)
    if not st:
        # NOTE: no coordinate fallback here — the US bounds box necessarily
        # includes Canada/Mexico, and nearest() would pin Tijuana to San Diego
        return None, "no US state"
    geo = None
    try:
        lat, lng = float(addr["latitude"]), float(addr["longitude"])
        if (lat, lng) != (0.0, 0.0):
            if not in_us_bounds(lat, lng):
                return None, "outside US bounds"  # province-code collision
            geo = Flow(lat=round(lat, 5), lng=round(lng, 5))
    except (KeyError, TypeError, ValueError):
        pass

    day_raw = (row.get("field_6") or "").strip()
    days = parse_days(day_raw)
    if not days:
        return None, "no weekday"
    time = parse_time(row.get("field_82") or "")
    if not time:
        return None, "no time"

    city = (addr.get("city") or "").strip()
    group_no = (row.get("field_3") or "").strip()
    name = (row.get("field_2") or "").strip()
    if not name:
        name = (f"{city} Nar-Anon Family Group" if city
                else f"Nar-Anon Group {group_no or row['id']}")

    schedule = []
    qualifier = DAY_QUALIFIER_RE.search(day_raw)
    for day in days:
        entry = Flow(day=day, time=time)
        if qualifier:  # "2nd and 4th Wednesday" — keep the source wording
            entry["note"] = re.sub(r"\s+", " ", day_raw)[:100]
        schedule.append(entry)

    fmt = ("hybrid" if virtual and in_person else
           "online" if virtual else "in-person")
    rec = {
        "_state": st, "_place_slug": "online", "_name": name,
        "program": "nar-anon",
        "categories": ["recovery-meeting", "family-support"],
        "schedule": schedule,
        "format": fmt,
    }
    if "Narateen" in tags:
        rec["types"] = ["narateen"]

    if fmt != "online":
        geoid, place_slug = places.resolve(st, city)
        if not geoid and geo:
            near = places.nearest(geo["lat"], geo["lng"])
            if near and near[0] == st:
                _, geoid, place_slug = near
        rec["_place_slug"] = place_slug
        venue_name = strip_html(row.get("field_5") or "")
        if venue_name:
            rec["venue_name"] = venue_name
        if city:
            venue = {"street": strip_html(addr.get("street") or "") or None,
                     "city": city, "state": st}
            zipc = (addr.get("zip") or "").strip()
            if re.fullmatch(r"\d{5}(-\d{4})?", zipc):
                venue["zip"] = zipc
            rec["venue"] = Flow({k: v for k, v in venue.items() if v})
        if geoid:
            rec["place"] = geoid
        if geo:
            rec["geo"] = geo

    tz = (row.get("field_182") or "").strip()
    notes = strip_html(row.get("field_8") or "")
    if tz and fmt != "in-person":
        notes = f"{tz}. {notes}".strip(". ") + ("" if notes else "")
    if notes and len(notes) <= 400:
        rec["notes"] = notes

    langs = []
    for part in (row.get("field_93_raw") or []):
        code = LANGS.get(str(part).strip().lower())
        if code and code not in langs:
            langs.append(code)
    if langs:
        rec["languages"] = langs

    ext = Flow(knack=row["id"])
    if group_no:
        ext["naranon"] = group_no
    rec["external_ids"] = ext
    rec["sources"] = [source_id]
    rec["verified"] = Flow(on=today(), method="api")
    return rec, None


def main(argv):
    force = "--force" in argv
    places = Places()

    first = fetch_page(1, force)
    total_pages = int(first.get("total_pages") or 0)
    total_records = int(first.get("total_records") or 0)
    if total_pages < 5 or total_records < 900:
        raise SystemExit(f"naranon: implausible table size "
                         f"({total_records} records / {total_pages} pages)")
    print(f"naranon: {total_records} rows worldwide, {total_pages} pages")

    source_id = write_source(
        "naranon", "group-database",
        kind="api-feed", publisher="Nar-Anon Family Groups WSO",
        title="Nar-Anon WSO group database (Knack API)",
        url="https://www.nar-anon.org/find-a-meeting", tier="primary",
    )

    records, seen_ext, seen_exact = [], set(), set()
    skips: dict[str, int] = {}
    raw = 0
    for page in range(1, total_pages + 1):
        data = first if page == 1 else fetch_page(page, force)
        for row in data.get("records") or []:
            raw += 1
            rec, why = build_record(row, places, source_id)
            if rec is None:
                skips[why] = skips.get(why, 0) + 1
                continue
            entry = rec["schedule"][0]
            exact = (rec["_name"].lower(), entry["day"], entry["time"],
                     rec["_state"], rec["_place_slug"])
            if row["id"] in seen_ext or exact in seen_exact:
                continue
            seen_ext.add(row["id"])
            seen_exact.add(exact)
            records.append(rec)

    by_fmt: dict[str, int] = {}
    for r in records:
        by_fmt[r["format"]] = by_fmt.get(r["format"], 0) + 1
    print(f"naranon: kept {len(records)} US of {raw} raw ({by_fmt}); skips: {skips}")
    # Of the 1,241 worldwide rows (2026-07), 581 are non-US and 33 inactive —
    # the US active ceiling is ~625, so the floor sits just under that.
    if len(records) < 550:
        raise SystemExit(f"naranon: only {len(records)} US meetings — expected 550+; aborting")
    replace_records("meetings", source_id, records)


if __name__ == "__main__":
    main(sys.argv[1:])
