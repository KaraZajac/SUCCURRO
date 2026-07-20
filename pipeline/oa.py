"""Overeaters Anonymous meetings -> meeting records (recovery-meeting).

oa.org's finder is a WordPress endpoint: POST /wp-json/oa-meetings/v1/
meetings_search with {"paged": N, "tzdb": ..., "base_url": ...} returns
{html, found, max_pages} — 20 table rows per page, 47 pages, 928 meetings
worldwide (2026-07). That is far below OA's historic "~6,000 meetings"
claim; the finder is evidently the post-pandemic registered-meeting list —
reported, not padded.

Quirk that shapes this module: every time in the search HTML — including
Face to Face rows — is converted to the requested tzdb, so a Pennsylvania
6:30 PM under America/Chicago is really 7:30 PM Eastern. Meeting detail
pages (/meetings/<id>/) carry the *original* local "Monday 7:30 PM", a
timezone label, and the duration, so the search sweep supplies metadata
(name, types, address, languages, topics) and a per-meeting detail crawl
supplies day/time/duration. Rows repeat one meeting id per weekday; rows
are merged per id and the detail page's full day list wins.

US filter: the location meta ends in "United States". Online/phone rows
that carry only "United States" with no state cannot be sharded (records
are state-keyed) and are skipped with a count — this loses a large slice
of the online list and is reported. Caches: sources/oa/search/p<N>.json
and sources/oa/meetings/<id>.html.

Usage: python3 -m pipeline.oa [--force]
"""
import html as htmllib
import json
import re
import sys
import time as _time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .bmlt import norm_state
from .emit import Places, replace_records, today, write_source
from .util import Flow, ROOT, SOURCES, UA, fetch, slugify

API = "https://oa.org/wp-json/oa-meetings/v1/meetings_search"
TZDB = "America/Chicago"
DETAIL_URL = "https://oa.org/meetings/{}/"

DAYS = {"sunday": "sun", "monday": "mon", "tuesday": "tue", "wednesday": "wed",
        "thursday": "thu", "friday": "fri", "saturday": "sat"}
LANGS = {"english": "en", "spanish": "es", "french": "fr", "portuguese": "pt",
         "german": "de", "italian": "it", "hebrew": "he", "russian": "ru",
         "greek": "el", "farsi": "fa", "persian": "fa", "arabic": "ar",
         "polish": "pl", "dutch": "nl", "swedish": "sv", "danish": "da",
         "finnish": "fi", "norwegian": "no", "japanese": "ja"}

ROW_SPLIT = re.compile(r'meeting-results__tr meeting-results__tr--publish')
MID_RE = re.compile(r'Meeting #:</strong></span>\s*<span class="notranslate">(\d+)')
NAME_RE = re.compile(r'name-link[^>]*>\s*(.*?)\s*</a>', re.S)
TYPE_RE = re.compile(r'meeting-results__type[^"]*">\s*([^<]*?)\s*<')
META_RE = re.compile(r'meeting-results__meta">\s*(.*?)\s*</div>', re.S)
LANG_RE = re.compile(r'meeting-lang">([^<]+)<')
TOPIC_RE = re.compile(r'<strong>Topics:</strong>\s*([^<]+)')
ROW_DAY_RE = re.compile(r'time-day-day[^>]*>(\w+)')
ROW_TIME_RE = re.compile(r'time-day-time"><strong>(\d{1,2}):(\d{2})<span[^>]*>([AP])M')
# detail page: <h2 class="meeting__header-subheading...">Monday 7:30 PM</h2>
DETAIL_DAYTIME_RE = re.compile(
    r"meeting__header-subheading[^>]*>\s*(Sunday|Monday|Tuesday|Wednesday"
    r"|Thursday|Friday|Saturday)[^<\d]*(\d{1,2}):(\d{2})\s*([AP])M", re.I)
DETAIL_TZ_RE = re.compile(r'oa-meeting-timezone[^>]*>([^<]+)<')
DETAIL_DUR_RE = re.compile(r"(\d+)\s*Minutes")
ZIP_RE = re.compile(r"^\d{5}(-\d{4})?$")


def api_page(page: int, force: bool) -> dict:
    cache = SOURCES / "oa" / "search" / f"p{page:02d}.json"
    if not cache.exists() or force:
        cache.parent.mkdir(parents=True, exist_ok=True)
        _time.sleep(1.0)
        body = json.dumps({"paged": page, "tzdb": TZDB,
                           "base_url": "https://oa.org/find-a-meeting/"}).encode()
        req = Request(API, data=body, headers={
            "Content-Type": "application/json", "User-Agent": UA})
        try:
            with urlopen(req, timeout=120) as resp:
                cache.write_bytes(resp.read())
        except (HTTPError, URLError, TimeoutError) as e:
            raise SystemExit(f"oa: search page {page} failed ({e})")
        print(f"fetched search p{page} -> {cache.relative_to(ROOT)}")
    return json.loads(cache.read_text())


def clean(text: str) -> str:
    return re.sub(r"\s+", " ", htmllib.unescape(re.sub(r"<[^>]+>", " ", text))).strip()


def parse_meta(raw: str):
    """Location cell -> (street, city, state, zip, us) — meta lines are
    '<street><br><city, State Name, zip><br>United States' for f2f, or
    '<State Name><br>United States' / 'United States' / '<Country>' online."""
    lines = [clean(part) for part in re.split(r"<br\s*/?>", raw)]
    lines = [l for l in lines if l]
    if not lines or lines[-1] != "United States":
        return None, None, None, None, False
    lines = lines[:-1]
    if not lines:
        return None, None, None, None, True  # US but stateless
    citystate = lines[-1]
    street = ", ".join(lines[:-1]) or None
    parts = [p.strip() for p in citystate.split(",") if p.strip()]
    zipc = None
    if parts and ZIP_RE.match(parts[-1]):
        zipc = parts.pop()[:5]
    if not parts:
        return street, None, None, zipc, True
    state_raw = parts[-1]
    city = ", ".join(parts[:-1]) or None
    return street, city, state_raw, zipc, True


def build_meeting(mid, rows, places, source_id, force, stats):
    """All search rows for one meeting id -> (record, None) or (None, why)."""
    row = rows[0]
    types_raw = set()
    for r in rows:
        types_raw.update(TYPE_RE.findall(r))
    if types_raw == {"Non-Real Time"}:
        return None, "non-real-time"
    f2f = "Face to Face" in types_raw
    online = "Online" in types_raw or "Phone" in types_raw

    mm = META_RE.search(row)
    street, city, state_raw, zipc, us = parse_meta(mm.group(1) if mm else "")
    if not us:
        return None, "non-US"
    st = norm_state(state_raw or "", places.by_state)
    if not st:
        # online rows tagged only "United States": no state to shard under
        return None, "US but no state"

    name = clean(NAME_RE.search(row).group(1)) if NAME_RE.search(row) else ""
    notes = None
    if name.startswith("*"):
        notes = name.lstrip("* ")
        name = ""
    if not name or name.lower() == "location":
        name = f"OA Meeting #{mid}"

    # detail page: original local day/time (search HTML is tz-converted)
    schedule, tz_label = [], None
    try:
        page = fetch(DETAIL_URL.format(mid),
                     SOURCES / "oa" / "meetings" / f"{mid}.html",
                     force=force).read_text()
        dur = None
        dm = DETAIL_DUR_RE.search(page)
        if dm and 0 < int(dm.group(1)) <= 480:
            dur = int(dm.group(1))
        tm = DETAIL_TZ_RE.search(page)
        if tm and clean(tm.group(1)):
            tz_label = clean(tm.group(1))
        seen_days = set()
        for day_name, hh, mins, ap in DETAIL_DAYTIME_RE.findall(page):
            day = DAYS[day_name.lower()]
            if day in seen_days:
                continue
            seen_days.add(day)
            h = int(hh) % 12 + (12 if ap.upper() == "P" else 0)
            entry = Flow(day=day, time=f"{h:02d}:{mins}")
            if dur:
                entry["duration_min"] = dur
            schedule.append(entry)
    except SystemExit as e:
        stats["detail_fail"] = stats.get("detail_fail", 0) + 1
        print(f"WARNING: oa meeting {mid}: {e}")
        if stats["detail_fail"] > 60:
            raise SystemExit("oa: >60 detail-page fetch failures — aborting")
    if not schedule:
        # fall back to the tz-converted search rows, flagged as Central
        seen_days = set()
        for r in rows:
            dm, tmm = ROW_DAY_RE.search(r), ROW_TIME_RE.search(r)
            if not dm or not tmm or dm.group(1).lower() not in DAYS:
                continue
            day = DAYS[dm.group(1).lower()]
            if day in seen_days:
                continue
            seen_days.add(day)
            h = int(tmm.group(1)) % 12 + (12 if tmm.group(3) == "P" else 0)
            schedule.append(Flow(day=day, time=f"{h:02d}:{tmm.group(2)}",
                                 note="US Central Time"))
        if not schedule:
            return None, "no schedule"

    rec = {
        "_state": st, "_place_slug": "online", "_name": name,
        "program": "oa",
        "categories": ["recovery-meeting"],
        "schedule": schedule,
        "format": "hybrid" if f2f and online else
                  "in-person" if f2f else "online",
    }
    types = []
    if "Phone" in types_raw and not f2f:
        types.append("phone")
    topm = TOPIC_RE.search(row)
    if topm:
        for part in topm.group(1).split(","):
            token = slugify(clean(part))
            if token and token not in types and len(types) < 8:
                types.append(token)
    if types:
        rec["types"] = types

    if f2f:
        geoid, place_slug = places.resolve(st, city or "")
        rec["_place_slug"] = place_slug
        if city:
            venue = {"street": street, "city": city, "state": st}
            if zipc:
                venue["zip"] = zipc
            rec["venue"] = Flow({k: v for k, v in venue.items() if v})
        if geoid:
            rec["place"] = geoid

    if tz_label and rec["format"] != "in-person":
        notes = f"{notes}. {tz_label}" if notes else tz_label
    if notes and len(notes) <= 400:
        rec["notes"] = notes

    langs = []
    for r in rows:
        for lm in LANG_RE.findall(r):
            code = LANGS.get(clean(lm).lower())
            if code and code not in langs:
                langs.append(code)
    if langs:
        rec["languages"] = langs

    rec["url"] = DETAIL_URL.format(mid)
    rec["external_ids"] = Flow(oa=mid)
    rec["sources"] = [source_id]
    rec["verified"] = Flow(on=today(), method="api")
    return rec, None


def main(argv):
    force = "--force" in argv
    places = Places()

    first = api_page(1, force)
    found, max_pages = int(first.get("found") or 0), int(first.get("max_pages") or 0)
    if found < 500 or not max_pages:
        raise SystemExit(f"oa: implausible search result (found={found})")
    print(f"oa: finder lists {found} meetings worldwide, {max_pages} pages "
          f"(OA historically claims ~6,000 — the finder under-lists; reported as found)")

    source_id = write_source(
        "oa", "meeting-finder",
        kind="api-feed", publisher="Overeaters Anonymous",
        title="Overeaters Anonymous meeting finder (oa.org)",
        url="https://oa.org/find-a-meeting/", tier="primary",
    )

    by_mid: dict[str, list[str]] = {}
    for page in range(1, max_pages + 1):
        data = first if page == 1 else api_page(page, force)
        rows = ROW_SPLIT.split(data.get("html") or "")[1:]
        for row in rows:
            m = MID_RE.search(row)
            if m:
                by_mid.setdefault(m.group(1), []).append(row)
    print(f"oa: {sum(len(v) for v in by_mid.values())} rows, "
          f"{len(by_mid)} distinct meetings")

    records, seen_exact = [], set()
    skips: dict[str, int] = {}
    stats: dict[str, int] = {}
    for mid in sorted(by_mid, key=int):
        rec, why = build_meeting(mid, by_mid[mid], places, source_id, force, stats)
        if rec is None:
            skips[why] = skips.get(why, 0) + 1
            continue
        entry = rec["schedule"][0]
        exact = (rec["_name"].lower(), entry["day"], entry["time"],
                 rec["_state"], rec["_place_slug"])
        if exact in seen_exact:
            continue
        seen_exact.add(exact)
        records.append(rec)

    by_fmt: dict[str, int] = {}
    for r in records:
        by_fmt[r["format"]] = by_fmt.get(r["format"], 0) + 1
    print(f"oa: kept {len(records)} US ({by_fmt}); skips: {skips}; "
          f"detail fetch failures: {stats.get('detail_fail', 0)}")
    # 2026-07 reality: 940 distinct meetings in the finder; ~342 foreign,
    # ~214 online rows tagged only "United States" (no state to shard under),
    # leaving ~376 keepable — floor set just below that.
    if len(records) < 340:
        raise SystemExit(f"oa: only {len(records)} US meetings — expected 340+; aborting")
    replace_records("meetings", source_id, records)


if __name__ == "__main__":
    main(sys.argv[1:])
