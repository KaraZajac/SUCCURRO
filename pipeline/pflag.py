"""PFLAG chapter directory -> org records (lgbtq / family-support), plus a
chapter-page crawl -> meeting records for chapters that list their meetings.

The find-a-chapter page embeds every chapter as a JSON string in its inline
`tmscripts` config object — one GET, no API. Every chapter also has a
pflag.org/chapter/<slug>/ page whose "Chapter Meetings and Events" feed is
server-rendered: one `<div class="event anim-me">` per dated instance with a
month/dates/year span, h3 title, optional description paragraph, an optional
Location block (<strong>venue</strong><br>street<br>City, ST ZIP) and a
uniform Time block ("7:00pm–8:30pm EDT"). Recurring meetings appear as several
future instances of the same title; the recurrence phrasing, when present,
lives in the description ("Third Tuesday of each month"). Pages are fetched
throttled (util.get sleeps per host) and cached under sources/pflag/pages/.

Chapter orgs stay owned by pflag/chapter-directory; meetings get their own
source id (pflag/chapter-meetings) so ownership is clean. Support-meeting
events with a parseable day+time become meeting records; meeting-ish schedule
text that can't be shaped into a schedule is appended to the chapter org's
description instead. One-off socials/fundraisers/talks are skipped.

Facts-only re-expression, attributed (see DATA-RIGHTS.md).

Usage: python3 -m pipeline.pflag [--force]
"""
import datetime
import html as htmllib
import json
import re
import sys
from collections import Counter

from .emit import Places, norm, replace_records, today, write_source
from .util import DATA, Flow, SOURCES, fetch, load_yaml

URL = "https://pflag.org/findachapter/"

LOC_RE = re.compile(r"^(?P<city>.+?),\s*(?P<state>[A-Z]{2})\s*(?P<zip>\d{5})?(-\d{4})?$")
PHONE_RE = re.compile(r"\(?(\d{3})\)?[\s./-]?\s*(\d{3})[\s.-]?(\d{4})")

# --- chapter-page event feed ------------------------------------------------

EVENT_RE = re.compile(
    r'<div class="event anim-me">(.*?)(?=<div class="event anim-me">|</section>)', re.S)
EV_DATE_RE = re.compile(
    r'<span class="month">([A-Za-z]+)</span>.*?<span class="dates">(\d+)</span>'
    r'<span class="year[^"]*">(\d{4})</span>', re.S)
EV_TITLE_RE = re.compile(r"<h3>(.*?)</h3>", re.S)
EV_DESC_RE = re.compile(r'<p class="medium slim">(.*?)</p>', re.S)
EV_TIME_RE = re.compile(r"<h5>Time</h5>\s*(.*?)\s*</div>", re.S)
EV_VENUE_RE = re.compile(r"<h5>Location</h5>\s*<p>(.*?)</p>", re.S)
TIME_RANGE_RE = re.compile(
    r"(\d{1,2})(?::(\d{2}))?\s*(am|pm)\s*[–—-]\s*(\d{1,2})(?::(\d{2}))?\s*(am|pm)"
    r"\s*([A-Z]{2,4})?", re.I)
# the recurrence phrase, kept verbatim as the schedule note ("3rd Tuesday of
# each month" preferred over a bare "monthly")
RECUR_RE = re.compile(
    r"((?:1st|2nd|3rd|4th|5th|first|second|third|fourth|last|every|each)\b"
    r"[^.!;]{0,80}?(?:day|week|month)[a-z]*)", re.I)
RECUR_WORD_RE = re.compile(r"\b(bi-?weekly|monthly|weekly)\b", re.I)
# recurring meetings are often listed per month as "July Monthly Meeting" or
# "Fort Collins August Support" — the month word is instance noise
MONTH_WORD_RE = re.compile(
    r"[.\s:–-]*\b(january|february|march|april|may|june|july|august|september|"
    r"october|november|december)\b[.\s:–-]*", re.I)
# one-off gatherings that mention "meeting" but aren't the recurring group
ONEOFF_RE = re.compile(
    r"\b(annual|holiday|festival|picnic|potluck|party|gala|fundrais|kickoff)", re.I)
MEETINGISH_RE = re.compile(
    r"\b(meeting|support group|support (?:zoom|space|circle)|peer support|"
    r"support meet|connects|drop-?in)\b", re.I)
VIRTUAL_RE = re.compile(r"\b(zoom|virtual|online|google meet|video call)\b", re.I)
MONTHS = {m: i + 1 for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun",
     "jul", "aug", "sep", "oct", "nov", "dec"])}
DAY_TOKENS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
DAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday",
             "Saturday", "Sunday"]
NTH = {1: "1st", 2: "2nd", 3: "3rd", 4: "4th", 5: "5th"}
# lines that leaked meeting prose into the directory's location field
PROSE_RE = re.compile(r"\bmeet(?:ings?|s)?\b", re.I)


def strip_tags(fragment: str) -> str:
    text = htmllib.unescape(re.sub(r"<[^>]+>", " ", fragment))
    return re.sub(r"\s+", " ", text).replace("\xa0", " ").strip()


def parse_location(location: str) -> tuple[dict, list[str]]:
    """'115 Gregg Avenue<br>Aiken, SC 29801<br>US' -> (address dict, prose).

    A couple of chapters put meeting prose in the location field; those lines
    are returned separately instead of polluting the street."""
    parts = [p.strip() for p in location.split("<br>") if p.strip() and p.strip() != "US"]
    if not parts:
        return {}, []
    m = LOC_RE.match(parts[-1])
    if not m:
        return {}, []
    addr = {"city": m["city"], "state": m["state"].lower()}
    if m["zip"]:
        addr["zip"] = m["zip"]
    streets = [p for p in parts[:-1] if not PROSE_RE.search(p)]
    prose = [p for p in parts[:-1] if PROSE_RE.search(p)]
    if streets:
        addr = {"street": ", ".join(streets), **addr}
    return addr, prose


def parse_time(text: str):
    """'7:00pm–8:30pm EDT' -> ('19:00', 90, 'EDT')."""
    m = TIME_RANGE_RE.search(text)
    if not m:
        return None, None, None
    h1, m1, mer1, h2, m2, mer2, tz = m.groups()
    start = int(h1) % 12 * 60 + int(m1 or 0) + (720 if mer1.lower() == "pm" else 0)
    end = int(h2) % 12 * 60 + int(m2 or 0) + (720 if mer2.lower() == "pm" else 0)
    dur = end - start
    return (f"{start // 60:02d}:{start % 60:02d}",
            dur if 0 < dur <= 480 else None, tz)


def parse_venue(fragment: str) -> tuple[str | None, dict]:
    """Location block -> (venue name, address dict). Lines: <strong>name
    </strong> / street / 'City, ST ZIP' / a Get-directions anchor."""
    nm = re.search(r"<strong>(.*?)</strong>", fragment, re.S)
    name = strip_tags(nm.group(1)) if nm else None
    body = re.sub(r"<a\s.*?</a>", "", fragment, flags=re.S)
    if nm:
        body = body.replace(nm.group(0), "")
    lines = [strip_tags(ln) for ln in re.split(r"<br\s*/?>", body)]
    lines = [ln for ln in lines if ln and ln.upper() != "TBD"]
    addr = {}
    for i, ln in enumerate(lines):
        m = LOC_RE.match(ln)
        if m:
            addr = {"city": m["city"], "state": m["state"].lower()}
            if m["zip"]:
                addr["zip"] = m["zip"]
            if i >= 1:
                addr = {"street": ", ".join(lines[:i]), **addr}
            break
    return name, addr


def parse_events(page: str) -> list[dict]:
    """Chapter page -> event-instance dicts (title, date, time, ...)."""
    i = page.find("Chapter Meetings and Events")
    if i < 0:
        return []
    sec = page[i:]
    if "No listed Chapter Meetings and Events" in sec:
        return []
    events = []
    for ev in EVENT_RE.findall(sec):
        tm, dm, timem = EV_TITLE_RE.search(ev), EV_DATE_RE.search(ev), EV_TIME_RE.search(ev)
        if not tm or not dm or not timem:
            continue
        try:
            date = datetime.date(int(dm.group(3)), MONTHS[dm.group(1).lower()[:3]],
                                 int(dm.group(2)))
        except (KeyError, ValueError):
            continue
        time, dur, tz = parse_time(strip_tags(timem.group(1)))
        desc = EV_DESC_RE.search(ev)
        venue_m = EV_VENUE_RE.search(ev)
        venue_name, venue_addr = parse_venue(venue_m.group(1)) if venue_m else (None, {})
        events.append({
            "title": strip_tags(tm.group(1)),
            "date": date, "time": time, "duration": dur, "tz": tz,
            "desc": strip_tags(desc.group(1)) if desc else "",
            "venue_name": venue_name, "venue_addr": venue_addr,
            "virtual": bool(VIRTUAL_RE.search(ev)),
        })
    return events


def build_meeting(instances: list[dict]) -> dict | None:
    """Instances of one (chapter, title) -> meeting fields, or None if no
    parseable time. Day comes from the instance dates' weekday; the recurrence
    phrase (or the nth-weekday pattern the listed dates show) is the note."""
    timed = [e for e in instances if e["time"]]
    if not timed:
        return None
    days = Counter(e["date"].weekday() for e in timed)
    weekday = days.most_common(1)[0][0]
    timed = [e for e in timed if e["date"].weekday() == weekday]
    first = min(timed, key=lambda e: e["date"])
    text = first["title"] + ". " + first["desc"]
    note = None
    m = RECUR_RE.search(text)
    if m:
        note = re.sub(r"\s+", " ", m.group(1)).strip(" ,")[:120]
    elif len(timed) > 1:  # derive the pattern the listed instances show
        nths = {(e["date"].day - 1) // 7 + 1 for e in timed}
        ordered = sorted(timed, key=lambda e: e["date"])
        deltas = {(b["date"] - a["date"]).days for a, b in zip(ordered, ordered[1:])}
        if len(nths) == 1:
            note = f"{NTH[nths.pop()]} {DAY_NAMES[weekday]} of the month"
        elif deltas and max(deltas) <= 8:
            note = "weekly"
        else:
            note = "recurring; see chapter page for dates"
    if not note:
        w = RECUR_WORD_RE.search(text)
        note = (w.group(1).lower() if w
                else f"listed for {first['date'].strftime('%b %-d, %Y')}")
    if first["tz"]:
        note += f" ({first['tz']})"
    entry = Flow(day=DAY_TOKENS[weekday], time=first["time"])
    if first["duration"]:
        entry["duration_min"] = first["duration"]
    entry["note"] = note
    if first["venue_addr"] or (first["venue_name"] and not first["virtual"]):
        fmt = "hybrid" if first["virtual"] else "in-person"
    elif first["virtual"]:
        fmt = "online"
    else:
        fmt = "in-person"  # local chapters default to meeting in person
    return {"entry": entry, "format": fmt, "first": first}


def main(argv):
    force = "--force" in argv
    places = Places()
    cache = SOURCES / "pflag" / "findachapter.html"
    html = fetch(URL, cache, force=force).read_text()

    i = html.find("tmscripts = ")
    if i < 0:
        raise SystemExit("pflag: tmscripts config not found — page layout changed")
    config, _ = json.JSONDecoder().raw_decode(html, i + len("tmscripts = "))
    chapters = json.loads(config["chapter_data"])
    if len(chapters) < 200:
        raise SystemExit(f"pflag: only {len(chapters)} chapters — expected ~345; aborting")

    source_id = write_source(
        "pflag", "chapter-directory",
        kind="directory", publisher="PFLAG National",
        title="PFLAG Find a Chapter",
        url=URL, tier="primary",
    )
    meet_source = write_source(
        "pflag", "chapter-meetings",
        kind="directory", publisher="PFLAG National",
        title="PFLAG chapter pages — Chapter Meetings and Events feeds",
        url=URL, tier="primary",
    )

    records, proto_meetings = [], []
    stats = Counter()
    for ch in chapters:
        name = (ch.get("chapter_name") or "").strip()
        addr, prose = parse_location(ch.get("location") or "")
        st = addr.get("state")
        if not name or not st or st not in places.by_state:
            continue
        geoid, place_slug = places.resolve(st, addr.get("city", ""))
        rec = {
            "_state": st, "_place_slug": "", "_name": name,
            "categories": ["lgbtq", "family-support", "peer-support"],
            "parent_org": "us/pflag",
            "address": Flow(addr),
        }
        if geoid:
            rec["place"] = geoid
        try:
            rec["geo"] = Flow(lat=round(float(ch["latitude"]), 5),
                              lng=round(float(ch["longitude"]), 5))
        except (KeyError, TypeError, ValueError):
            pass
        if ch.get("phone"):
            pm = PHONE_RE.search(ch["phone"])
            rec["phone"] = "-".join(pm.groups()) if pm else ch["phone"].strip()
        if ch.get("email"):
            rec["email"] = ch["email"].strip()
        website = (ch.get("website") or ch.get("url") or "").strip()
        if website:
            rec["website"] = website
        if prose:
            # meeting prose that leaked into the directory's location field
            rec["description"] = " ".join(prose)[:400]
            stats["descriptions appended"] += 1
        rec["sources"] = [source_id]
        rec["verified"] = Flow(on=today(), method="scrape")
        records.append(rec)

        # ---- chapter-page crawl: the Chapter Meetings and Events feed ----
        page_url = (ch.get("url") or "").strip()
        slug = page_url.rstrip("/").split("/")[-1] if page_url else ""
        if not slug:
            stats["no chapter url"] += 1
            continue
        try:
            page = fetch(page_url, SOURCES / "pflag" / "pages" / f"{slug}.html",
                         force=force).read_text(errors="replace")
        except SystemExit as e:
            print(f"WARNING: pflag {slug}: {e}")
            stats["page fetch failed"] += 1
            continue
        events = parse_events(page)
        if not events:
            stats["no events listed"] += 1
            continue
        stats["chapters with events"] += 1
        unparseable = []
        by_title: dict[str, list[dict]] = {}
        for ev in events:
            # "July Monthly Meeting" / "August Monthly Meeting" are instances
            # of one recurring meeting — group on the month-stripped title
            stripped = re.sub(r"\s+", " ", MONTH_WORD_RE.sub(" ", ev["title"]))
            ev["title"] = stripped.strip(" -–:") or ev["title"]
            by_title.setdefault(norm(ev["title"]), []).append(ev)
        for instances in by_title.values():
            first = instances[0]
            text = first["title"] + " " + first["desc"]
            recurring = bool(RECUR_RE.search(text) or len(instances) > 1)
            if not MEETINGISH_RE.search(text) and not (
                    recurring and re.search(r"support|parent|famil", text, re.I)):
                stats["one-off events skipped"] += 1
                continue
            if ONEOFF_RE.search(first["title"]) and not RECUR_RE.search(text) \
                    and len(instances) == 1:
                stats["one-off events skipped"] += 1
                continue
            built = build_meeting(instances)
            if not built:
                stats["meetings without parseable time"] += 1
                unparseable.append(
                    f"{first['title']} ({first['date'].strftime('%b %-d, %Y')})")
                continue
            stats["meetings"] += 1
            mrec = {
                "_state": st,
                "_place_slug": place_slug if built["format"] != "online" else "online",
                "_name": first["title"][:80],
                "program": "pflag",
                "categories": ["lgbtq", "family-support", "peer-support"],
                "_org_key": (st, norm(name)),
                "schedule": [built["entry"]],
                "format": built["format"],
            }
            f = built["first"]
            if f["venue_name"]:
                mrec["venue_name"] = f["venue_name"][:100]
            if f["venue_addr"]:
                mrec["venue"] = Flow(f["venue_addr"])
                vgeo, vslug = places.resolve(f["venue_addr"]["state"],
                                             f["venue_addr"]["city"])
                mrec["_state"] = f["venue_addr"]["state"]
                if built["format"] != "online":
                    mrec["_place_slug"] = vslug
                if vgeo:
                    mrec["place"] = vgeo
            elif built["format"] != "online" and geoid:
                mrec["place"] = geoid
                if "geo" in rec:
                    mrec["geo"] = rec["geo"]
            descs = {norm(e["desc"]) for e in instances}
            # a description that changes per instance is that month's speaker
            # topic, not a fact about the recurring meeting — keep it only
            # when it is stable across the listed instances
            if f["desc"] and len(descs) == 1 and norm(f["desc"]) != norm(f["title"]):
                mrec["notes"] = f["desc"][:200]
            mrec["url"] = page_url
            mrec["external_ids"] = Flow(pflag_chapter=slug)
            mrec["sources"] = [meet_source]
            mrec["verified"] = Flow(on=today(), method="scrape")
            proto_meetings.append(mrec)
        if unparseable:
            # meeting-ish schedule text that couldn't be shaped into a
            # schedule lands in the chapter org's description
            text = "Listed meetings: " + "; ".join(unparseable)
            rec["description"] = (rec.get("description", "") + " " + text).strip()[:400]
            stats["descriptions appended"] += 1

    # the national umbrella org the chapters point at
    records.append({
        "_state": "us", "_place_slug": "", "_name": "PFLAG National",
        "id": "us/pflag",
        "categories": ["lgbtq", "family-support"],
        "website": "https://pflag.org",
        "service_area": Flow(kind="national"),
        "sources": [source_id],
        "verified": Flow(on=today(), method="scrape"),
    })

    replace_records("orgs", source_id, records)

    # chapter org ids are assigned at write time — map them back for the FK
    org_ids = {}
    for path in sorted((DATA / "orgs").rglob("*.yaml")):
        rec = load_yaml(path)
        if source_id in (rec.get("sources") or []):
            org_ids[(rec["id"].split("/")[0], norm(rec["name"]))] = rec["id"]
    linked = 0
    for mrec in proto_meetings:
        oid = org_ids.get(mrec.pop("_org_key"))
        if oid:
            mrec["org"] = oid
            linked += 1
        # keep key order: org right after categories
        tail = {k: mrec.pop(k) for k in list(mrec)
                if k not in ("_state", "_place_slug", "_name", "program",
                             "categories", "org")}
        mrec.update(tail)

    n = stats["meetings"]
    print(f"pflag: {stats['chapters with events']} of {len(chapters)} chapter pages "
          f"list events; {n} meetings parsed "
          f"({linked} linked to chapter orgs); stats: {dict(stats)}")
    if n < 10:
        raise SystemExit(f"pflag: only {n} meetings parsed — layout changed? "
                         "(orgs written; meetings left untouched)")
    replace_records("meetings", meet_source, proto_meetings)


if __name__ == "__main__":
    main(sys.argv[1:])
