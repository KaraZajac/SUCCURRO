"""TAPS (Tragedy Assistance Program for Survivors) care groups -> meeting records.

taps.org's care-group finder is a public Teamup calendar; the share URL itself
serves JSON: GET teamup.com/<key>/events?startDate=&endDate= returns every
event instance in the window, unauthenticated. Instances carry the series
RRULE (almost all monthly by ordinal weekday, e.g. FREQ=MONTHLY;BYDAY=3MO),
title, a location that is either a full street address or "Zoom"/"Virtual"/
"Online Only", an event timezone, and a Zoom registration link. A ~90-day
window catches every monthly recurrence; instances collapse into unique
series on series_id (name+day+time is NOT unique: Pensacola runs two
same-named groups on the 2nd and 3rd Thursday).

Quirks: start_dt/end_dt are rendered in the calendar's default zone (ET)
regardless of the event's own tz field, so meeting-local times come from
converting the instance start into the event tz (zoneinfo). The monthly
phrasing ("3rd Monday") is rebuilt from the RRULE and kept as a schedule
note. One-off no-RRULE events are seasonal placeholders ("NO MEETINGS IN
JUNE...") and are skipped. Titles flag hybrid/online-only groups whose
location field alone would mislead ("ONLINE and IN-PERSON" with a street
address, "(ONLINE ONLY)" with none). Online groups shard under us/online.

Usage: python3 -m pipeline.taps [--force]
"""
import datetime
import json
import re
import sys
from collections import Counter
from zoneinfo import ZoneInfo

from .bmlt import STATE_NAMES, norm_state
from .emit import Places, replace_records, today, write_source
from .util import Flow, SOURCES, fetch

CAL_KEY = "ksassqzqxz1eetim1g"
CAL_URL = f"https://teamup.com/{CAL_KEY}"
WINDOW_DAYS = 90

ZIP_RE = re.compile(r"(\d{5})(?:-\d{4})?\s*$")
STATE_CODE_RE = re.compile(r"[,\s]([A-Za-z]{2})$")
BYDAY_RE = re.compile(r"^(-?\d)?(MO|TU|WE|TH|FR|SA|SU)$")
HREF_RE = re.compile(r'href="(https?://[^"]+)"')
HYBRID_RE = re.compile(r"online\s*(?:and|&)\s*in.?person", re.I)
ONLINE_ONLY_RE = re.compile(r"online\s*only", re.I)

DAY_TOKEN = {"MO": "mon", "TU": "tue", "WE": "wed", "TH": "thu",
             "FR": "fri", "SA": "sat", "SU": "sun"}
WEEKDAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
ONLINE_LOCS = {"", "zoom", "virtual", "online", "online only"}
DAY_NAME = {"mon": "Monday", "tue": "Tuesday", "wed": "Wednesday",
            "thu": "Thursday", "fri": "Friday", "sat": "Saturday",
            "sun": "Sunday"}
ORDINAL = {1: "1st", 2: "2nd", 3: "3rd", 4: "4th", 5: "5th", -1: "last"}
TZ_ABBR = {"America/New_York": "ET", "America/Chicago": "CT",
           "America/Denver": "MT", "America/Boise": "MT",
           "America/Los_Angeles": "PT", "America/Phoenix": "MST",
           "America/Anchorage": "AKT", "Pacific/Honolulu": "HST"}


def parse_rrule(rrule: str) -> dict:
    parts = dict(p.split("=", 1) for p in rrule.split(";") if "=" in p)
    byday = []
    for tok in filter(None, parts.get("BYDAY", "").split(",")):
        m = BYDAY_RE.match(tok)
        if m:
            byday.append((int(m[1]) if m[1] else None, DAY_TOKEN[m[2]]))
    return {"freq": parts.get("FREQ", ""),
            "interval": int(parts.get("INTERVAL", 1)), "byday": byday}


def parse_address(loc: str, by_state):
    """'Venue, 123 Main St, City, ST 12345' -> (venue_name, street, city, st,
    zip) or None. Tolerates spelled-out states ('Golden Colorado 80401'),
    missing city/state comma ('Dallas TX 75039'), and 'IL60563'."""
    zm = ZIP_RE.search(loc)
    if not zm:
        return None
    zipc, head = zm[1], loc[: zm.start()].strip(" ,-")
    st = None
    cm = STATE_CODE_RE.search(head)
    if cm and norm_state(cm[1], by_state):
        st, head = norm_state(cm[1], by_state), head[: cm.start(1)]
    else:
        words = head.replace(",", " ").split()
        for n in (2, 1):  # 'new york' before 'york'
            name = " ".join(words[-n:]).lower()
            if len(words) > n and name in STATE_NAMES:
                st = norm_state(name, by_state)
                head = head[: head.lower().rfind(name)]
                break
    if not st:
        return None
    segs = [s.strip() for s in re.split(r",| - ", head) if s.strip()]
    if not segs:
        return None
    city = segs.pop()
    venue_name = segs.pop(0) if segs and not segs[0][0].isdigit() else None
    return venue_name, ", ".join(segs) or None, city, st, zipc


def build_record(e: dict, places: Places, source_id: str):
    name = re.sub(r"\s+", " ", e["title"]).strip()
    if not name or name.upper().startswith("NO MEETINGS"):
        return None, "seasonal placeholder"
    rr = parse_rrule(e["rrule"])
    if rr["freq"] not in ("WEEKLY", "MONTHLY"):
        return None, f"unhandled FREQ {rr['freq'] or '?'}"

    tz = ZoneInfo(e["tz"])
    start = datetime.datetime.fromisoformat(e["start_dt"]).astimezone(tz)
    end = datetime.datetime.fromisoformat(e["end_dt"]).astimezone(tz)
    day = WEEKDAYS[start.weekday()]
    dur = int((end - start).total_seconds() // 60)

    # recurrence phrase: ordinal from RRULE BYDAY (fall back to day-of-month),
    # weekday from the meeting-local start
    phrase = None
    if rr["freq"] == "MONTHLY":
        nth = next((n for n, _ in rr["byday"] if n), (start.day - 1) // 7 + 1)
        phrase = f"{ORDINAL.get(nth, f'{nth}th')} {DAY_NAME[day]}"
        if rr["interval"] > 1:
            phrase += f", every {rr['interval']} months"
    elif rr["interval"] > 1:
        phrase = f"every {rr['interval']} weeks"

    loc = re.sub(r"\s+", " ", e.get("location") or "").strip()
    addr = None
    if loc.lower() not in ONLINE_LOCS:
        addr = parse_address(loc, places.by_state)
        if not addr:
            return None, "unparsed location"
    if addr and HYBRID_RE.search(name):
        fmt = "hybrid"
    elif addr and not ONLINE_ONLY_RE.search(name):
        fmt = "in-person"
    else:
        fmt, addr = "online", None

    entry = Flow(day=day, time=start.strftime("%H:%M"))
    if 0 < dur <= 480:
        entry["duration_min"] = dur
    note = [phrase] if phrase else []
    if fmt != "in-person" and e["tz"] in TZ_ABBR:
        note.append(TZ_ABBR[e["tz"]])
    if note:
        entry["note"] = ", ".join(note)

    rec = {"_state": "us", "_place_slug": "online", "_name": name,
           "program": "taps",
           "categories": ["veterans", "family-support", "peer-support"],
           "schedule": [entry], "format": fmt}
    if addr:
        venue_name, street, city, st, zipc = addr
        rec["_state"] = st
        geoid, rec["_place_slug"] = places.resolve(st, city)
        if venue_name:
            rec["venue_name"] = venue_name
        venue = {"street": street, "city": city, "state": st, "zip": zipc}
        rec["venue"] = Flow({k: v for k, v in venue.items() if v})
        if geoid:
            rec["place"] = geoid
    if fmt != "in-person":
        hm = HREF_RE.search((e.get("custom") or {}).get("registration_link") or "")
        if hm:
            rec["conference_url"] = hm[1]
    rec["url"] = CAL_URL
    rec["external_ids"] = Flow(taps_teamup=str(e["series_id"] or e["id"]))
    rec["sources"] = [source_id]
    rec["verified"] = Flow(on=today(), method="api")
    return rec, None


def main(argv):
    force = "--force" in argv
    places = Places()

    start = datetime.date.today()
    end = start + datetime.timedelta(days=WINDOW_DAYS)
    url = f"{CAL_URL}/events?startDate={start}&endDate={end}"
    cache = SOURCES / "taps" / f"events-{start}.json"
    events = json.loads(fetch(url, cache, force=force).read_text())["events"]
    if len(events) < 100:
        raise SystemExit(f"taps: only {len(events)} event instances in a "
                         f"{WINDOW_DAYS}-day window — calendar moved?")

    # collapse recurring instances into series; keep each series' earliest
    # instance. No-RRULE one-offs are announcements, not groups.
    series: dict = {}
    skips = Counter()
    for e in sorted(events, key=lambda e: e["start_dt"]):
        if not e.get("rrule"):
            skips["one-off (no rrule)"] += 1
            continue
        series.setdefault(e["series_id"] or e["id"], e)
    print(f"taps: {len(events)} instances -> {len(series)} recurring series "
          f"({start}..{end})")

    source_id = write_source(
        "taps", "care-groups-calendar",
        kind="api-feed", publisher="Tragedy Assistance Program for Survivors",
        title="TAPS care groups calendar (public Teamup feed)",
        url=CAL_URL, tier="primary",
    )

    records, seen_exact = [], set()
    for e in series.values():
        rec, why = build_record(e, places, source_id)
        if rec is None:
            skips[why] += 1
            print(f"taps: skip {e['series_id'] or e['id']} — {why}: "
                  f"{e['title'][:60]!r} @ {(e.get('location') or '')[:40]!r}")
            continue
        sched = rec["schedule"][0]
        exact = (rec["_name"].lower(), sched["day"], sched["time"],
                 sched.get("note"), rec["_state"], rec["_place_slug"])
        if exact in seen_exact:
            skips["duplicate"] += 1
            continue
        seen_exact.add(exact)
        records.append(rec)

    by_fmt = Counter(r["format"] for r in records)
    print(f"taps: kept {len(records)} of {len(series)} series "
          f"({dict(by_fmt)}); skips: {dict(skips)}")
    if len(records) < 40:
        raise SystemExit(f"taps: only {len(records)} groups — expected 40+; "
                         "aborting")
    replace_records("meetings", source_id, records)


if __name__ == "__main__":
    main(sys.argv[1:])
