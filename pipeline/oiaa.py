"""OIAA (Online Intergroup of AA) meetings -> meeting records (recovery-meeting).

aa-intergroup.org/meetings is backed by Code for Recovery's central-query API
(https://central-query.apps.code4recovery.org/api/v1/meetings). The API looks
windowed — a bare GET returns only ~50-120 rows — because its defaults are
start=now, hours=1: it answers "what is meeting in the next hour". Reading the
route source (github.com/code4recovery/central-query, meetings.controller.ts +
utils/dates.ts) shows the real contract:

- each meeting document carries an `rtc` key "W:HH:MM" — UTC weekday (Mon=1..
  Sun=7) + UTC start time — and the query matches rtc against the window
  [start - 9min, start + hours];
- params: start (ISO datetime; only its weekday+time matter), hours (1-168),
  limit (capped at 1000 — hours=168 alone truncates), scheduled=false for the
  handful of meetings with no fixed weekly time, plus type/formats/features/
  communities/languages/nameQuery filters (facet codes from /meetings/facets).

So the full corpus is a sweep: 42 windows of 4 hours across a week (each well
under the 1000 cap; halved automatically if one ever hits it), deduped by slug
(windows overlap by the server's 9-minute grace). Meeting-local day/time come
from converting nextEventUTC into the row's IANA timezone (zoneinfo); the zone
is kept in the schedule entry note.

Anonymity: groupEmail/groupPhone/groupNotes/notes are never stored — only the
conference URL, join notes (meeting ID/passcode), and schedule facts.

Usage: python3 -m pipeline.oiaa [--force]
"""
import datetime
import json
import re
import sys
from urllib.parse import quote
from zoneinfo import ZoneInfo

from .emit import replace_records, today, write_source
from .util import Flow, ROOT, SOURCES, get, slugify

API = "https://central-query.apps.code4recovery.org/api/v1/meetings"
SITE = "https://aa-intergroup.org/meetings/"

DAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")  # isoweekday 1..7
URL_RE = re.compile(r"^https?://\S+$")
LANG_RE = re.compile(r"^[a-z]{2,3}$")

# facet codes -> taxonomy-style tokens (central-query src/common/types.ts and
# /meetings/facets descriptions, 2026-07)
CODES = {
    # type
    "O": "open", "C": "closed",
    # formats
    "11": "11th-step", "12x12": "12-steps-12-traditions", "A": "secular",
    "ABSI": "as-bill-sees-it", "B": "big-book", "BE": "newcomer",
    "D": "discussion", "DR": "daily-reflections", "GR": "grapevine",
    "H": "birthday", "LIT": "literature", "LS": "living-sober",
    "MED": "meditation", "SP": "speaker", "ST": "step-study",
    "TR": "tradition-study",
    # features
    "AL-AN": "al-anon", "AL": "alateen", "ASL": "asl", "BA": "babysitting",
    "BRK": "breakfast", "CAN": "candlelight", "CF": "child-friendly",
    "DB": "digital-basket", "X": "wheelchair-access", "XB": "wheelchair-bathroom",
    "XT": "cross-talk", "POA": "proof-of-attendance", "OUT": "outdoor",
    "FF": "fragrance-free", "RSL": "russian-sign-language", "TC": "location-temporarily-closed",
    # communities
    "M": "men", "W": "women", "DD": "dual-diagnosis", "LGBTQ": "lgbtq",
    "Y": "young-people", "N": "native-american", "BI": "bisexual",
    "T": "transgender", "SEN": "seniors", "POC": "people-of-color",
    "P": "professionals", "NDG": "indigenous", "L": "lesbian", "G": "gay",
    "BV-I": "blind-visually-impaired", "D-HOH": "deaf-hard-of-hearing",
    "LO-I": "loners-isolationists",
}

WINDOW_HOURS = 4  # 42 windows/week; every probe stayed well under the 1000 cap


def fetch_window(start: datetime.datetime, hours: int, cache_stem: str,
                 force: bool) -> list:
    """One rtc window, cached. Recursively halves if it hits the row cap."""
    cache = SOURCES / "oiaa" / f"{cache_stem}.json"
    if cache.exists() and not force:
        rows = json.loads(cache.read_text())
    else:
        url = (f"{API}?start={quote(start.strftime('%Y-%m-%dT%H:%M:%SZ'))}"
               f"&hours={hours}&limit=1000")
        rows = json.loads(get(url))
        if not isinstance(rows, list):
            raise SystemExit(f"oiaa: window {cache_stem} returned non-list")
        if len(rows) < 1000:  # don't cache a truncated window
            cache.parent.mkdir(parents=True, exist_ok=True)
            cache.write_text(json.dumps(rows))
            print(f"fetched window {cache_stem} ({len(rows)} rows) "
                  f"-> {cache.relative_to(ROOT)}")
    if len(rows) >= 1000:
        if hours <= 1:
            raise SystemExit(f"oiaa: 1h window {cache_stem} still at row cap")
        half = hours // 2
        return (fetch_window(start, half, f"{cache_stem}a", force)
                + fetch_window(start + datetime.timedelta(hours=half), half,
                               f"{cache_stem}b", force))
    return rows


def build_record(row: dict, source_id: str):
    slug = (row.get("slug") or "").strip()
    if not slug:
        return None, "no slug"
    tz_name = (row.get("timezone") or "").strip()
    when = (row.get("nextEventUTC") or "").strip()
    try:
        utc = datetime.datetime.fromisoformat(when.replace("Z", "+00:00"))
        local = utc.astimezone(ZoneInfo(tz_name))
    except Exception:  # bad ISO string, empty/unknown zone (ZoneInfoNotFoundError)
        return None, "bad time/timezone"

    entry = Flow(day=DAYS[local.isoweekday() - 1],
                 time=f"{local.hour:02d}:{local.minute:02d}")
    dur = row.get("duration")
    if isinstance(dur, int) and 0 < dur <= 480:
        entry["duration_min"] = dur
    entry["note"] = tz_name

    name = re.sub(r"\s+", " ", row.get("name") or "").strip()
    if not name:
        name = f"AA Online Meeting {slug}"

    rec = {
        "_state": "us", "_place_slug": "online", "_name": name,
        "program": "aa",
        "categories": ["recovery-meeting"],
        "schedule": [entry],
        "format": "online",
    }

    types = []
    codes = [row.get("type")] + list(row.get("formats") or []) + \
        list(row.get("features") or []) + list(row.get("communities") or [])
    for code in codes:
        token = CODES.get(str(code or "").strip().upper()) or slugify(str(code or ""))
        if token and token not in types and len(types) < 8:
            types.append(token)
    if types:
        rec["types"] = types

    conf = (row.get("conference_url") or "").strip()
    if URL_RE.match(conf):
        rec["conference_url"] = conf
    # join facts only (meeting ID / passcode) — never groupNotes/notes/emails
    join = re.sub(r"\s+", " ", row.get("conference_url_notes") or "").strip()
    if join and "@" not in join and len(join) <= 200:
        rec["notes"] = join

    langs = [l for l in (row.get("languages") or [])
             if isinstance(l, str) and LANG_RE.match(l)]
    if langs:
        rec["languages"] = langs

    rec["url"] = f"{SITE}{slug}/"
    rec["external_ids"] = Flow(oiaa=slug)
    rec["sources"] = [source_id]
    rec["verified"] = Flow(on=today(), method="api")
    return rec, None


def main(argv):
    force = "--force" in argv

    # any Monday 00:00 UTC works — the server matches on weekday+time only
    now = datetime.datetime.now(datetime.timezone.utc)
    base = (now - datetime.timedelta(days=now.isoweekday() - 1)).replace(
        hour=0, minute=0, second=0, microsecond=0)

    source_id = write_source(
        "oiaa", "central-query",
        kind="api-feed", publisher="Online Intergroup of Alcoholics Anonymous",
        title="OIAA online meeting directory (central-query API)",
        url=SITE, tier="primary",
    )

    records, seen_slug, skips, raw = [], set(), {}, 0
    for i in range(168 // WINDOW_HOURS):
        start = base + datetime.timedelta(hours=i * WINDOW_HOURS)
        rows = fetch_window(start, WINDOW_HOURS, f"window-{i:02d}", force)
        for row in rows:
            if not isinstance(row, dict):
                continue
            raw += 1
            slug = (row.get("slug") or "").strip()
            if slug in seen_slug:
                continue  # 9-minute window overlap / duplicates
            rec, why = build_record(row, source_id)
            if rec is None:
                skips[why] = skips.get(why, 0) + 1
                continue
            seen_slug.add(slug)
            records.append(rec)

    print(f"oiaa: kept {len(records)} meetings from {raw} rows across "
          f"{168 // WINDOW_HOURS} windows; skips: {skips or 'none'}")
    if len(records) < 800:
        raise SystemExit(f"oiaa: only {len(records)} meetings — expected 800+; aborting")
    replace_records("meetings", source_id, records)


if __name__ == "__main__":
    main(sys.argv[1:])
