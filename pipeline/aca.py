"""Adult Children of Alcoholics (ACA/ACoA) meetings -> meeting records.

adultchildren.org runs the WSO Meetings plugin. Its REST search
(POST /wp-json/wsom/v1/meeting-search/) *can* be driven without a browser —
the param combo that every naive attempt missed (captured from a real
browser XHR with Playwright, 2026-07):

- send scalars only — page, countryFromIP, Timezone, LangValue, SearchText,
  Country, State, searchLocation, radius, I_GID, R_GID, showEditLink;
  omitting any of them 500s, but the Focus[]/Type[]/otherNotes[]/m_type[]
  arrays must be OMITTED entirely (sending them empty filters to count:0 —
  the failure mode in the research notes);
- Timezone must be a real IANA zone and radius non-empty (radius=30);
- X-WP-Nonce header from the /meeting-search/ page's wsomMeetingSearch JS
  config, plus that page's cookies.

Country=United States returns filtered_count 2,070 of all_count 2,991 in
30-row JSON pages (results carry SID, WSONumber, MeetName, m_type, own
Timezone, meeting-local Time_Local, DayCode 1=Sun..7=Sat, Focus/Type,
address fields, Notes/Location HTML, LangValue, OpenClosed). Day/time are
taken from the unadjusted DayCode/Time_Local pair (the *_TZ_Adjusted
fields are relative to the query timezone). Rows without a US state
(mostly telephone/online) cannot shard into state files and are skipped
with a count. Raw pages cached under sources/aca/; the nonce is refetched
every run (it is session-bound and expires).

Usage: python3 -m pipeline.aca [--force]
"""
import html as htmllib
import http.cookiejar
import json
import re
import sys
import time as _time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import HTTPCookieProcessor, Request, build_opener

from .bmlt import norm_state
from .emit import Places, replace_records, today, write_source
from .util import BROWSER_UA, Flow, ROOT, SOURCES, slugify

SEARCH_PAGE = "https://adultchildren.org/meeting-search/"
API = "https://adultchildren.org/wp-json/wsom/v1/meeting-search/"

DAY_CODES = {"1": "sun", "2": "mon", "3": "tue", "4": "wed",
             "5": "thu", "6": "fri", "7": "sat"}
LANGS = {"english": "en", "spanish": "es", "french": "fr", "german": "de",
         "russian": "ru", "farsi": "fa", "persian": "fa", "italian": "it",
         "portuguese": "pt", "japanese": "ja", "hebrew": "he", "greek": "el",
         "polish": "pl", "dutch": "nl", "finnish": "fi", "swedish": "sv",
         "danish": "da", "turkish": "tr", "korean": "ko"}
TIME_RE = re.compile(r"(\d{1,2}):(\d{2})\s*([ap])\.?m", re.I)
URL_IN_HTML_RE = re.compile(r"https?://[^\s<>\"']+")
ZIP_RE = re.compile(r"^\d{5}(-\d{4})?$")


class Session:
    """Cookie-carrying opener bound to a fresh page nonce."""

    def __init__(self):
        self.opener = build_opener(HTTPCookieProcessor(http.cookiejar.CookieJar()))
        req = Request(SEARCH_PAGE, headers={"User-Agent": BROWSER_UA})
        try:
            html = self.opener.open(req, timeout=120).read().decode()
        except (HTTPError, URLError, TimeoutError) as e:
            raise SystemExit(f"aca: cannot load search page ({e})")
        m = re.search(r'"nonce":"([0-9a-f]+)"', html)
        if not m:
            raise SystemExit("aca: no wsom nonce on the search page — layout changed?")
        self.nonce = m.group(1)

    def page(self, page: int, force: bool) -> dict:
        cache = SOURCES / "aca" / f"page-{page:02d}.json"
        if cache.exists() and not force:
            return json.loads(cache.read_text())
        cache.parent.mkdir(parents=True, exist_ok=True)
        _time.sleep(1.0)
        body = urlencode([
            ("page", str(page)), ("countryFromIP", "United States"),
            ("Timezone", "America/New_York"), ("LangValue", ""),
            ("SearchText", ""), ("Country", "United States"), ("State", ""),
            ("searchLocation", ""), ("radius", "30"),
            ("I_GID", ""), ("R_GID", ""), ("showEditLink", "false"),
        ]).encode()
        req = Request(API, data=body, headers={
            "User-Agent": BROWSER_UA, "X-WP-Nonce": self.nonce,
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "Referer": SEARCH_PAGE,
        })
        try:
            data = self.opener.open(req, timeout=120).read()
        except (HTTPError, URLError, TimeoutError) as e:
            raise SystemExit(f"aca: search page {page} failed ({e})")
        parsed = json.loads(data)
        if "results" not in parsed:
            raise SystemExit(f"aca: page {page} returned no results key: {str(parsed)[:200]}")
        cache.write_bytes(data)
        print(f"fetched search page {page} -> {cache.relative_to(ROOT)}")
        return parsed


def strip_html(raw: str) -> str:
    return re.sub(r"\s+", " ", htmllib.unescape(re.sub(r"<[^>]+>", " ", raw or ""))).strip()


def build_record(row: dict, places: Places, source_id: str):
    if (row.get("Country") or "").strip() != "United States":
        return None, "non-US"
    st = norm_state((row.get("State") or "").strip(), places.by_state)
    if not st:
        return None, "US but no state"
    day = DAY_CODES.get(str(row.get("DayCode") or "").strip())
    tm = TIME_RE.search(row.get("Time_Local") or "")
    if not day or not tm:
        return None, "no day/time"
    h = int(tm[1]) % 12 + (12 if tm[3].lower() == "p" else 0)
    time = f"{h:02d}:{tm[2]}"

    name = strip_html(row.get("MeetName") or "")
    if not name:
        name = f"ACA Meeting {row.get('WSONumber') or row.get('SID')}"

    m_type = (row.get("m_type") or "").strip().lower()
    has_addr = bool((row.get("Address") or "").strip() or (row.get("City") or "").strip())
    virtual_info = strip_html(row.get("virtualInfo") or "")
    if m_type == "meeting":
        fmt = "hybrid" if virtual_info else "in-person"
    else:
        fmt = "online"  # online + telephone

    rec = {
        "_state": st, "_place_slug": "online", "_name": name,
        "program": "aca",
        "categories": ["recovery-meeting", "family-support"],
        "schedule": [Flow(day=day, time=time)],
        "format": fmt,
    }
    types = []
    if m_type == "telephone":
        types.append("phone")
    oc = (row.get("OpenClosed") or "").strip().upper()
    if oc == "O":
        types.append("open")
    elif oc == "C":
        types.append("closed")
    for field in ("Focus", "Type"):
        for part in (row.get(field) or "").split(","):
            token = slugify(part.strip())
            if token and token not in types and len(types) < 8:
                types.append(token)
    if types:
        rec["types"] = types

    if fmt != "online" and has_addr:
        city = (row.get("City") or "").strip()
        geoid, place_slug = places.resolve(st, city)
        rec["_place_slug"] = place_slug
        venue_name = strip_html(row.get("Location") or "")
        if venue_name and len(venue_name) <= 120:
            rec["venue_name"] = venue_name
        if city:
            venue = {"street": (row.get("Address") or "").strip() or None,
                     "city": city, "state": st}
            zipc = (row.get("PostalCode") or "").strip()
            if ZIP_RE.match(zipc):
                venue["zip"] = zipc[:5]
            rec["venue"] = Flow({k: v for k, v in venue.items() if v})
        if geoid:
            rec["place"] = geoid

    if fmt != "in-person":
        um = URL_IN_HTML_RE.search(row.get("virtualInfo") or "") or \
             URL_IN_HTML_RE.search(row.get("Location") or "")
        if um:
            rec["conference_url"] = htmllib.unescape(um.group(0)).rstrip(".,);")

    notes_parts = []
    for field in ("Notes", "Location") if fmt == "online" else ("Notes",):
        text = strip_html(row.get(field) or "")
        if text:
            notes_parts.append(text)
    notes = " ".join(notes_parts)
    if notes and len(notes) <= 400:
        rec["notes"] = notes

    code = LANGS.get((row.get("LangValue") or "").strip().lower())
    if code:
        rec["languages"] = [code]

    website = (row.get("pri_website") or "").strip()
    if re.match(r"^https?://\S+$", website):
        rec["url"] = website

    ext = Flow(aca=str(row.get("SID")))
    wso = (row.get("WSONumber") or "").strip()
    if wso:
        ext["wso"] = wso
    rec["external_ids"] = ext
    rec["sources"] = [source_id]
    rec["verified"] = Flow(on=today(), method="api")
    return rec, None


def main(argv):
    force = "--force" in argv
    places = Places()
    session = Session()

    first = session.page(1, force)
    pages = int(first.get("pages") or 0)
    filtered = int(first.get("filtered_count") or 0)
    if pages < 10 or filtered < 1000:
        raise SystemExit(f"aca: implausible result set (pages={pages}, "
                         f"filtered={filtered})")
    print(f"aca: {filtered} US meetings ({first.get('all_count')} worldwide), "
          f"{pages} pages")

    source_id = write_source(
        "aca", "meeting-search",
        kind="api-feed", publisher="Adult Children of Alcoholics WSO",
        title="ACA WSO meeting search (wsom REST API)",
        url=SEARCH_PAGE, tier="primary",
    )

    records, seen_sid, seen_exact = [], set(), set()
    skips: dict[str, int] = {}
    raw = 0
    for page in range(1, pages + 1):
        data = first if page == 1 else session.page(page, force)
        for row in data.get("results") or []:
            raw += 1
            rec, why = build_record(row, places, source_id)
            if rec is None:
                skips[why] = skips.get(why, 0) + 1
                continue
            sid = rec["external_ids"]["aca"]
            entry = rec["schedule"][0]
            exact = (rec["_name"].lower(), entry["day"], entry["time"],
                     rec["_state"], rec["_place_slug"])
            if sid in seen_sid or exact in seen_exact:
                continue
            seen_sid.add(sid)
            seen_exact.add(exact)
            records.append(rec)

    by_fmt: dict[str, int] = {}
    for r in records:
        by_fmt[r["format"]] = by_fmt.get(r["format"], 0) + 1
    print(f"aca: kept {len(records)} of {raw} US rows ({by_fmt}); skips: {skips}")
    if len(records) < 1000:
        raise SystemExit(f"aca: only {len(records)} meetings — expected 1,000+; aborting")
    replace_records("meetings", source_id, records)


if __name__ == "__main__":
    main(sys.argv[1:])
