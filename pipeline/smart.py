"""SMART Recovery USA meetings -> meeting records (recovery-meeting).

meetings.smartrecovery.org is a server-rendered Django app (Pathminder
Meetings platform) behind Cloudflare — there is no JSON meeting API; the
finder UI only does location-radius searches (geocoding via a
location.pathminder.net proxy). But /sitemap.xml enumerates every meeting
detail page (~1,250 as of 2026-07), and each detail page carries a
machine-readable AddEvent calendar block (meeting-local start/end +
IANA timezone + RRULE BYDAY + program/audience/language labels), a street
address card for in-person meetings, and a Pathcheck join link for online
meetings. So: crawl sitemap -> detail pages, cached one file per meeting
under sources/smart/meetings/.

Cloudflare's challenge is passive as of 2026-07: plain urllib with the
browser UA passes, so no headless capture step is needed. If that changes,
re-capture with Playwright (site/node_modules has playwright; save each
detail page's HTML to the same cache paths) and re-run — the module builds
entirely from cache. Pages that fail to fetch or parse are skipped with a
warning (and not cached); re-runs fetch only what's missing. Detail pages
carry no coordinates, so records get place FKs via city resolution but no
geo — the validator soft-finds that.

Usage: python3 -m pipeline.smart [--force]
"""
import re
import sys
from urllib.parse import unquote

from .bmlt import norm_state
from .emit import Places, replace_records, today, write_source
from .util import BROWSER_UA, Flow, SOURCES, fetch, slugify

SITEMAP = "https://meetings.smartrecovery.org/sitemap.xml"
MEETING_URL = "https://meetings.smartrecovery.org/meetings/{}/"

BYDAY = {"SU": "sun", "MO": "mon", "TU": "tue", "WE": "wed",
         "TH": "thu", "FR": "fri", "SA": "sat"}
DAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")  # date.weekday() order

LANGS = {"english": "en", "spanish": "es", "french": "fr", "portuguese": "pt",
         "german": "de", "italian": "it", "mandarin": "zh", "chinese": "zh",
         "russian": "ru", "vietnamese": "vi", "korean": "ko", "japanese": "ja",
         "farsi": "fa", "persian": "fa", "arabic": "ar", "hindi": "hi",
         "tagalog": "tl", "polish": "pl", "american sign language": "ase"}

COMMENT_RE = re.compile(r"<!--.*?-->", re.S)
TAG_RE = re.compile(r"<[^>]+>")
ADDEVENT_RE = re.compile(r'class="addeventatc.*?</div>', re.S)
SPAN_RE = re.compile(
    r'<span[^>]*class="(start|end|timezone|title|description|recurring)">(.*?)</span>', re.S)
# <title>SMART Recovery USA - Meeting #9234 Soquel, California</title>
TITLE_TAG_RE = re.compile(r"<title>[^<]*Meeting #(\d+)\s+([^<]*?)\s*</title>")
# AddEvent title: "... Meeting: #1067 - Global - West Coast Early Birds" — the part
# after the id is the meeting's display name when it isn't just "City, State"
AE_NAME_RE = re.compile(r"Meeting:\s*#\d+\s*-\s*(.*)$")
DATE_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})\s+(\d{2}):(\d{2})$")
DIRLINK_RE = re.compile(r'href="https://www\.google\.com/maps/dir//([^"?]+)')
PATHCHECK_RE = re.compile(r'href="(https://[a-z0-9.-]*pathcheck\.net/j/[^"?]+)')
VENUE_RE = re.compile(r'fa-location-arrow[^>]*></i>[^<]*</div>.*?<p class="card-text">'
                      r"\s*(.*?)</p>", re.S)
LABEL_RE = re.compile(r"<strong>(Program|Audiences|Languages spoken):</strong>([^<]*)")


def day_of(y: int, m: int, d: int) -> str:
    import datetime
    return DAYS[datetime.date(y, m, d).weekday()]


def parse_city_state(blurb: str, by_state):
    """'Soquel, California' -> ('Soquel', 'ca'); None state if not a US state."""
    if "," not in blurb:
        return blurb.strip(), None
    city, state_raw = blurb.rsplit(",", 1)
    return city.strip(), norm_state(state_raw, by_state)


def parse_address(raw: str, by_state):
    """Decoded maps-dir string '4525 Soquel Drive, Soquel, CA, 95073' (state may
    be a full name, zip may be attached or missing, trailing ', USA' possible)
    -> (street, city, state, zip) with state None when not a US state."""
    s = unquote(raw).strip().strip(",")
    s = re.sub(r",?\s*(USA|United States)$", "", s).strip().strip(",")
    zm = re.search(r"(\d{5})(?:-\d{4})?$", s)
    zipc = zm.group(1) if zm else None
    if zm:
        s = s[: zm.start()].strip().strip(",")
    parts = [p.strip() for p in s.split(",") if p.strip()]
    if len(parts) < 2:
        return None, None, None, None
    st = norm_state(parts[-1], by_state)
    if len(parts) == 2:
        # "street+city, ST" (no comma before the city — "305 Elmwood Ave.
        # Alderson, WV"): city can't be split out; caller falls back to the
        # page's home city. Otherwise assume "city-only, ST-less" garble.
        return (None, None, st, zipc) if st else (None, parts[-1], None, zipc)
    if st is None:  # "street, city, State Name" with a stray trailing token
        return None, None, None, None
    if re.fullmatch(r"\d{5}(-\d{4})?", parts[-2]):  # "street, city, zip, ST"
        zipc = zipc or parts[-2][:5]
        parts.pop(-2)
        if len(parts) < 3:
            return None, None, st, zipc
    return ", ".join(parts[:-2]) or None, parts[-2], st, zipc


# Per-brand knobs so lifering.py (same Pathminder platform) can reuse parse_page.
BRAND = {
    "program": "smart", "ext_key": "smart", "prefix": "SMART Recovery",
    "url": MEETING_URL,
    # program labels that don't merit inclusion in a fallback meeting name
    "generic_labels": {"4-point recovery", ""},
}


def parse_page(html: str, mid: int, places: Places, source_id: str, brand=BRAND):
    """One meeting detail page -> record dict, or (None, why) on skip."""
    page = COMMENT_RE.sub("", html)
    block = ADDEVENT_RE.search(page)
    if not block:
        return None, "no addeventatc block"
    spans = {k: v.strip() for k, v in SPAN_RE.findall(block.group(0))}

    dm = DATE_RE.match(spans.get("start", ""))
    if not dm:
        return None, "unparseable start time"
    time = f"{dm[4]}:{dm[5]}"
    days = []
    rrule = spans.get("recurring", "")
    for code in re.findall(r"[A-Z]{2}", rrule.partition("BYDAY=")[2].split(";")[0]):
        if code in BYDAY and BYDAY[code] not in days:
            days.append(BYDAY[code])
    if not days:
        days = [day_of(int(dm[1]), int(dm[2]), int(dm[3]))]
    duration = None
    em = DATE_RE.match(spans.get("end", ""))
    if em:
        duration = (int(em[4]) * 60 + int(em[5])) - (int(dm[4]) * 60 + int(dm[5]))
        if not 0 < duration <= 480:
            duration = None
    schedule = []
    for day in days:
        entry = Flow(day=day, time=time)
        if duration:
            entry["duration_min"] = duration
        iv = re.search(r"INTERVAL=(\d+)", rrule)
        if iv and int(iv[1]) > 1:
            entry["note"] = f"every {iv[1]} weeks"
        schedule.append(entry)

    tm = TITLE_TAG_RE.search(html)
    if not tm:
        return None, "unparseable title tag"
    home_blurb = tm[2].strip()
    home_city, home_st = parse_city_state(home_blurb, places.by_state)

    # the online card header (join link may instead say "contact the convenor")
    has_online = ("Meetings can typically be joined" in page
                  or "This online meeting is run out of" in page
                  or re.search(r"fa-video[^>]*></i>[^<]*Online Meeting", page) is not None)
    dirm = DIRLINK_RE.search(page)
    street = city = st = zipc = None
    if dirm:
        street, city, st, zipc = parse_address(dirm[1], places.by_state)
        if not (city and st) and home_city and home_st:
            # malformed address string ("Pleasant HIll. CA", missing state...):
            # keep the meeting, sited at its home city, without street detail
            street, city, st = None, home_city, home_st
    if dirm and city and st:
        fmt = "hybrid" if has_online else "in-person"
    elif has_online:
        fmt, city, st = "online", home_city, home_st
    else:
        return None, "neither online card nor address"
    if st is None:
        return None, "not a US state"

    labels = dict(LABEL_RE.findall(spans.get("description", "")))
    program_label = labels.get("Program", "").strip()
    name = None
    nm = AE_NAME_RE.search(spans.get("title", ""))
    if nm:
        candidate = nm[1].replace("&amp;", "&").strip()
        # LifeRing in-person titles read "#1038 - Benicia, California - Benicia
        # LifeRing": drop a leading home "City, State -" before judging the rest
        candidate = re.sub(rf"^{re.escape(home_blurb)}\s*-\s*", "", candidate,
                           flags=re.I).strip()
        # only a real name if it isn't just the home "City, State" repeated
        if candidate and slugify(candidate) != slugify(home_blurb):
            name = candidate
    if not name:
        name = f"{brand['prefix']} Meeting #{mid}"
        if program_label and program_label.lower() not in brand["generic_labels"]:
            label = program_label.replace("&amp;", "&")
            name = f"{brand['prefix']} {label} Meeting #{mid}"

    rec = {
        "_state": st, "_place_slug": "online", "_name": name,
        "program": brand["program"],
        "categories": ["recovery-meeting"],
        "schedule": schedule,
        "format": fmt,
    }
    types = []
    for label in (program_label, labels.get("Audiences", "")):
        for part in label.split(","):
            token = slugify(part.strip())
            if token and token not in types and len(types) < 8:
                types.append(token)
    if types:
        rec["types"] = types

    if fmt != "online":
        geoid, place_slug = places.resolve(st, city)
        rec["_place_slug"] = place_slug
        vm = VENUE_RE.search(page)
        if vm:
            first_line = TAG_RE.sub("\n", vm[1]).strip().split("\n")[0].strip()
            # the card's first line is the venue name unless it's just the address
            if first_line and not first_line[0].isdigit():
                rec["venue_name"] = first_line.replace("&amp;", "&")
        venue = {"street": street, "city": city, "state": st}
        if zipc:
            venue["zip"] = zipc
        rec["venue"] = Flow({k: v for k, v in venue.items() if v})
        if geoid:
            rec["place"] = geoid

    if has_online:
        jm = PATHCHECK_RE.search(page)
        if jm:
            rec["conference_url"] = jm[1]

    langs = []
    for part in labels.get("Languages spoken", "").split(","):
        code = LANGS.get(part.strip().lower())
        if code and code not in langs:
            langs.append(code)
    if langs:
        rec["languages"] = langs

    rec["url"] = brand["url"].format(mid)
    rec["external_ids"] = Flow(**{brand["ext_key"]: str(mid)})
    rec["sources"] = [source_id]
    rec["verified"] = Flow(on=today(), method="scrape")
    return rec, None


def crawl(ids, cache_dir, places: Places, source_id: str, force: bool, brand=BRAND):
    """Fetch + parse every meeting detail page; returns records. Shared with
    pipeline.lifering (same platform). Failures are skipped loudly; a cached
    page that no longer parses (e.g. a captured challenge page) is evicted."""
    tag = brand["ext_key"]
    records, seen_exact, fetch_failed, parse_failed = [], set(), [], []
    for mid in ids:
        cache = cache_dir / "meetings" / f"{mid}.html"
        try:
            html = fetch(brand["url"].format(mid), cache, force=force,
                         ua=BROWSER_UA).read_text()
        except SystemExit as e:
            print(f"WARNING: {tag} meeting {mid}: {e}")
            fetch_failed.append(mid)
            if len(fetch_failed) > 60:
                raise SystemExit(
                    f"{tag}: too many fetch failures — Cloudflare likely blocking; "
                    f"re-capture pages with a headless browser into {cache_dir}/meetings/")
            continue
        rec, why = parse_page(html, mid, places, source_id, brand)
        if rec is None:
            parse_failed.append(f"{mid} ({why})")
            # real pages without an AddEvent block exist (non-weekly schedules:
            # "first and third Monday..."); only evict what isn't a real page
            # (e.g. a captured Cloudflare challenge, which lacks the site chrome)
            if "addeventatc" in why and "athminder" not in html and cache.exists():
                cache.unlink()
            continue
        exact = (rec["_name"].lower(), rec["schedule"][0]["day"],
                 rec["schedule"][0]["time"], rec["_state"], rec["_place_slug"])
        if exact in seen_exact:
            continue
        seen_exact.add(exact)
        records.append(rec)

    by_fmt = {}
    for r in records:
        by_fmt[r["format"]] = by_fmt.get(r["format"], 0) + 1
    print(f"{tag}: kept {len(records)} ({by_fmt}), "
          f"{len(fetch_failed)} fetch failures, {len(parse_failed)} parse skips")
    if parse_failed:
        print("parse skips:", ", ".join(parse_failed[:20]),
              "..." if len(parse_failed) > 20 else "")
    return records


def main(argv):
    force = "--force" in argv
    places = Places()
    cache_dir = SOURCES / "smart"

    sitemap = fetch(SITEMAP, cache_dir / "sitemap.xml", force=force,
                    ua=BROWSER_UA).read_text()
    ids = sorted({int(m) for m in re.findall(
        r"<loc>https://meetings\.smartrecovery\.org/meetings/(\d+)/</loc>", sitemap)})
    if len(ids) < 500:
        raise SystemExit(f"smart: sitemap lists only {len(ids)} meetings — layout changed?")
    print(f"smart: {len(ids)} meetings in sitemap")

    source_id = write_source(
        "smart", "meeting-finder",
        kind="directory", publisher="SMART Recovery USA",
        title="SMART Recovery USA meeting finder (SMARTfinder)",
        url="https://meetings.smartrecovery.org/meetings/", tier="primary",
    )

    records = crawl(ids, cache_dir, places, source_id, force, brand=BRAND)
    if len(records) < 800:
        raise SystemExit(f"smart: only {len(records)} US meetings — expected 800+; aborting")
    replace_records("meetings", source_id, records)


if __name__ == "__main__":
    main(sys.argv[1:])
