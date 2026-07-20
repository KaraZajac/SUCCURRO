"""Gamblers Anonymous meetings -> meeting records (recovery-meeting).

gamblersanonymous.org runs WP Event Manager, but the meeting detail pages
enumerated by event_listing-sitemap{,2,3}.xml (2,996 pages worldwide) carry
an *empty* schema.org Event startDate and a literal "-" in their Date And
Time block — no meeting time is published there. The site's own finder is
the only surface that renders times: server-side search templates at
/usa-meetings/ (in-person, per-state, term=147) and /virtual-meetings/
(country search, term=133) return 5 cards per page with name, "Location:"
address string, "Time: 06:30 PM - 08:00 PM", and a description block
(venue name / meeting type / Zoom credentials). So we crawl the search
pages: 51 state searches + the United States virtual search, paginated,
cached one page per file under sources/gamblersanon/pages/ (resumable;
--force refetches). /phone-meetings/ is a static page with two US phone
meetings and no geography — not harvested.

Reality check vs the research note's "~2,996 US meetings": that figure is
the sitemap total, which includes international in-person meetings and the
virtual/phone listings. The finder yields ~1.3k US in-person + ~300 US
virtual, so the sanity floor here is 1,200.

Usage: python3 -m pipeline.gamblersanon [--force]
"""
import html as htmllib
import re
import sys
from urllib.parse import quote

from .bmlt import STATE_NAMES
from .emit import Places, replace_records, today, write_source
from .util import Flow, SOURCES, fetch

BASE = "https://gamblersanonymous.org"
# option values of the /usa-meetings/ state <select>, verbatim
STATES = [
    "Alabama", "Alaska", "Arizona", "Arkansas", "California", "Colorado",
    "Connecticut", "Delaware", "Florida", "Georgia", "Hawaii", "Idaho",
    "Illinois", "Indiana", "Iowa", "Kansas", "Kentucky", "Louisiana",
    "Maine", "Maryland", "Massachusetts", "Michigan", "Minnesota",
    "Mississippi", "Missouri", "Montana", "Nebraska", "Nevada",
    "New Hampshire", "New Jersey", "New Mexico", "New York",
    "North Carolina", "North Dakota", "Ohio", "Oklahoma", "Oregon",
    "Pennsylvania", "Rhode Island", "South Carolina", "South Dakota",
    "Tennessee", "Texas", "Utah", "Vermont", "Virginia", "Washington",
    "Washington D.C.", "West Virginia", "Wisconsin", "Wyoming",
]

DAY_TOKENS = {"sunday": "sun", "monday": "mon", "tuesday": "tue",
              "wednesday": "wed", "thursday": "thu", "friday": "fri",
              "saturday": "sat"}

CARD_RE = re.compile(
    r"<a href='([^']+)'><div style=\"border:1px solid #ccc[^\"]*\">\s*"
    r"<h4>(.*?)</h4>(.*?)</div></a>", re.S)
LOC_RE = re.compile(r"Location:\s*(.*?)</p>", re.S)
TIME_RE = re.compile(
    r"Time:\s*(\d{1,2})(?::(\d{2}))?\s*([AP])\.?M\.?"
    r"(?:\s*[-–]\s*(\d{1,2})(?::(\d{2}))?\s*([AP])\.?M\.?)?", re.I)
DESC_RE = re.compile(r"<div>(.*?)</div>\s*$", re.S)
DAY_RE = re.compile(r"[-–]\s*(Sunday|Monday|Tuesday|Wednesday|Thursday"
                    r"|Friday|Saturday)\s*$", re.I)
URL_RE = re.compile(r'href="(https?://[^"]+)"')
PAGED_RE = re.compile(r"paged=(\d+)")
ZIP_RE = re.compile(r"\b(\d{5})(?:-\d{4})?\b")
MAX_PAGES = 100  # per search; CA peaks at 25, virtual US at ~60


def clean(text: str) -> str:
    return re.sub(r"\s+", " ", htmllib.unescape(text)).strip()


def to_24h(hh: str, mm: str | None, ap: str) -> str:
    h = int(hh) % 12 + (12 if ap.upper() == "P" else 0)
    return f"{h:02d}:{mm or '00'}"


def norm_state_token(token: str, by_state) -> str | None:
    """'Alabama' / 'Washington D.C.' -> registry state code, else None."""
    key = re.sub(r"\s+", " ", token.replace(".", "")).strip().lower()
    if key in ("washington dc", "district of columbia"):
        return "dc" if "dc" in by_state else None
    code = STATE_NAMES.get(key)
    return code if code in by_state else None


def parse_location(loc: str, by_state):
    """'137 South Gay Street, Auburn, Alabama, 36830, United States' (zip may
    trail the country instead) -> (street, city, state, zip)."""
    zm = ZIP_RE.search(loc)
    zipc = zm.group(1) if zm else None
    parts = [p.strip() for p in loc.split(",")]
    parts = [p for p in parts
             if p and not re.fullmatch(r"(United States|USA)( \d{5}(-\d{4})?)?"
                                       r"|\d{5}(-\d{4})?", p, re.I)]
    for i in range(len(parts) - 1, -1, -1):
        st = norm_state_token(parts[i], by_state)
        if st:
            city = parts[i - 1] if i >= 1 else None
            street = ", ".join(parts[: i - 1]) or None if i >= 2 else None
            return street, city, st, zipc
    return None, None, None, zipc


def parse_virtual_name(name: str, by_state):
    """'Agawam, Massachusetts, United States' / 'Arizona, United States'
    -> (city or None, state)."""
    parts = [p.strip() for p in name.split(",")
             if p.strip() and not re.fullmatch(r"United States|USA", p.strip(), re.I)]
    if not parts:
        return None, None
    st = norm_state_token(parts[-1], by_state)
    city = ", ".join(parts[:-1]) or None
    return city, st


def external_id(url: str) -> str | None:
    m = re.search(r"/find-a-meeting/([^/?#]+)", url)
    if m:
        return m.group(1)
    m = re.search(r"[?&]p=(\d+)", url)
    return f"p{m.group(1)}" if m else None


def desc_lines(inner: str) -> list[str]:
    dm = DESC_RE.search(inner)
    if not dm:
        return []
    lines = [clean(p) for p in re.split(r"</p>|<br\s*/?>", dm.group(1))]
    return [re.sub(r"<[^>]+>", " ", l).strip() for l in lines if clean(re.sub(r"<[^>]+>", "", l))]


def meeting_types(text: str) -> list[str]:
    types = []
    low = text.lower()
    if "modified closed" in low:
        types.append("modified-closed")
    elif re.search(r"\bclosed\b", low):
        types.append("closed")
    if re.search(r"\bopen\b", low):
        types.append("open")
    return types


def parse_card(url, name_html, inner, virtual, places, source_id):
    """One search-result card -> (record, None) or (None, why)."""
    name = clean(name_html)
    dm = DAY_RE.search(name)
    if not dm:
        return None, "no weekday in name"
    day = DAY_TOKENS[dm.group(1).lower()]
    tm = TIME_RE.search(inner)
    if not tm:
        return None, "no time"
    time = to_24h(tm[1], tm[2], tm[3])
    entry = Flow(day=day, time=time)
    if tm[4]:
        end = to_24h(tm[4], tm[5], tm[6])
        dur = (int(end[:2]) * 60 + int(end[3:])) - (int(time[:2]) * 60 + int(time[3:]))
        if 0 < dur <= 480:
            entry["duration_min"] = dur

    lines = desc_lines(inner)
    desc_text = "; ".join(lines)

    if virtual:
        city, st = parse_virtual_name(DAY_RE.sub("", name).strip(" -–"), places.by_state)
        if not st:
            return None, "no US state in virtual name"
        street = zipc = None
        fmt = "in-person"  # overwritten below
    else:
        lm = LOC_RE.search(inner)
        if not lm:
            return None, "no location line"
        street, city, st, zipc = parse_location(clean(lm.group(1)), places.by_state)
        if not st:
            return None, "no US state in location"

    rec = {
        "_state": st, "_place_slug": "online", "_name": name,
        "program": "ga",
        "categories": ["recovery-meeting"],
        "schedule": [entry],
        "format": "online" if virtual else "in-person",
    }
    types = meeting_types(desc_text)
    if types:
        rec["types"] = types

    notes_lines = lines
    if not virtual:
        geoid, place_slug = places.resolve(st, city or "")
        rec["_place_slug"] = place_slug
        # first description line is usually the venue name
        if lines and not lines[0][0].isdigit() and not meeting_types(lines[0]):
            rec["venue_name"] = lines[0]
            notes_lines = lines[1:]
        if city:
            venue = {"street": street, "city": city, "state": st}
            if zipc:
                venue["zip"] = zipc
            rec["venue"] = Flow({k: v for k, v in venue.items() if v})
        if geoid:
            rec["place"] = geoid
    else:
        um = URL_RE.search(inner)
        if um:
            rec["conference_url"] = um.group(1)
        notes_lines = [l for l in lines if not l.lower().startswith("link")]

    notes = "; ".join(notes_lines)
    if notes and len(notes) <= 400:
        rec["notes"] = notes

    ext = external_id(url)
    if ext:
        rec["external_ids"] = Flow(gamblersanon=ext)
        if url.startswith(BASE + "/find-a-meeting/"):
            rec["url"] = url.split("?")[0]
    rec["sources"] = [source_id]
    rec["verified"] = Flow(on=today(), method="scrape")
    return rec, None


def crawl_search(label, url_fn, cache_dir, force, fail_state):
    """Paginate one search; yields (url, name_html, inner) card tuples."""
    max_page = 1
    page = 1
    while page <= min(max_page, MAX_PAGES):
        cache = cache_dir / f"{label}-p{page}.html"
        try:
            html = fetch(url_fn(page), cache, force=force).read_text()
            fail_state["run"] = 0
        except SystemExit as e:
            print(f"WARNING: gamblersanon {label} p{page}: {e}")
            fail_state["run"] += 1
            if fail_state["run"] > 60:
                raise SystemExit("gamblersanon: >60 consecutive fetch failures — aborting")
            page += 1
            continue
        seg = html.split('id="search-results"')[-1]
        cards = CARD_RE.findall(seg)
        if not cards and page == 1:
            break  # state with no meetings
        pages = [int(x) for x in PAGED_RE.findall(seg)]
        if pages:
            max_page = max(max_page, max(pages))
        yield from cards
        if not cards:
            break  # ran off the end (stale cached pagination)
        page += 1


def main(argv):
    force = "--force" in argv
    places = Places()
    cache_dir = SOURCES / "gamblersanon" / "pages"

    source_id = write_source(
        "gamblersanon", "meeting-search",
        kind="directory", publisher="Gamblers Anonymous",
        title="Gamblers Anonymous meeting finder (US in-person + virtual)",
        url="https://gamblersanonymous.org/find-a-meeting/", tier="primary",
    )

    records, seen_ext, seen_exact = [], set(), set()
    skips: dict[str, int] = {}
    fail_state = {"run": 0}

    def add_cards(cards, virtual):
        kept = 0
        for url, name_html, inner in cards:
            rec, why = parse_card(url, name_html, inner, virtual, places, source_id)
            if rec is None:
                skips[why] = skips.get(why, 0) + 1
                continue
            ext = (rec.get("external_ids") or {}).get("gamblersanon")
            entry = rec["schedule"][0]
            exact = (rec["_name"].lower(), entry["day"], entry["time"],
                     rec["_state"], rec["_place_slug"])
            if (ext and ext in seen_ext) or exact in seen_exact:
                continue
            if ext:
                seen_ext.add(ext)
            seen_exact.add(exact)
            records.append(rec)
            kept += 1
        return kept

    for state in STATES:
        def url_fn(page, state=state):
            return (f"{BASE}/usa-meetings/?city=&state={quote(state)}"
                    f"&zipcode=&radius=&weekday=&term=147&paged={page}")
        kept = add_cards(crawl_search(f"us-{state.lower().replace(' ', '-').replace('.', '')}",
                                      url_fn, cache_dir, force, fail_state), False)
        print(f"{state}: {kept} kept")

    def virtual_url(page):
        return (f"{BASE}/virtual-meetings/?city=&country=United+States"
                f"&weekday=&term=133&paged={page}")
    kept = add_cards(crawl_search("virtual-us", virtual_url, cache_dir, force,
                                  fail_state), True)
    print(f"virtual: {kept} kept")

    by_fmt: dict[str, int] = {}
    for r in records:
        by_fmt[r["format"]] = by_fmt.get(r["format"], 0) + 1
    print(f"gamblersanon: {len(records)} records ({by_fmt}); skips: {skips}")
    # The sitemap's 2,996 event pages span the whole world (plus virtual and
    # phone listings); the finder itself yields ~1.6k US meetings.
    if len(records) < 1200:
        raise SystemExit(f"gamblersanon: only {len(records)} records — expected 1,200+; aborting")
    replace_records("meetings", source_id, records)


if __name__ == "__main__":
    main(sys.argv[1:])
