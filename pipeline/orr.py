"""ORR refugee resettlement local affiliates -> org records.

The Office of Refugee Resettlement's "Find Resources and Contacts in Your
State" map page (acf.gov) links one page per participating state; each page
carries a uniform Local Area Affiliates table (CITY | LOCAL AFFILIATE |
TELEPHONE, affiliate cell usually linked to the agency website). Federal
public domain. Key Contacts (state coordinators — named people) are not
copied. acf.gov's WAF challenges non-browser clients, so fetches use
BROWSER_UA (rhy.py convention); pages cache under sources/orr/.

State pages carry their own "current as of" dates (2022-2025 at time of
writing); records are verified against the live federal page on each run. A
state page that 404s upstream (DC's hub link is broken as of 2026-07-21) is
skipped and reported; more than three broken states aborts the run so a WAF
change can't silently shrink the pull. Affiliates default to family-support
only — the table doesn't say which provide legal services, so
immigration-legal is never guessed.

Usage: python3 -m pipeline.orr [--force]
"""
import html
import re
import sys

from .emit import Places, norm, replace_records, today, write_source
from .util import BROWSER_UA, Flow, SOURCES, fetch

HUB = "https://acf.gov/orr/map/find-resources-and-contacts-your-state"

OPTION_RE = re.compile(r'<option value="(/orr/[^"]+)">([^<]+)</option>')
TABLE_RE = re.compile(r"<table.*?</table>", re.S)
ROW_RE = re.compile(r"<tr[^>]*>(.*?)</tr>", re.S)
CELL_RE = re.compile(r"<t[dh][^>]*>(.*?)</t[dh]>", re.S)
HREF_RE = re.compile(r'href="(https?://[^"]+)"')

STATE_NAMES = {
    "alabama": "al", "alaska": "ak", "arizona": "az", "arkansas": "ar",
    "california": "ca", "colorado": "co", "connecticut": "ct",
    "delaware": "de", "district of columbia": "dc", "florida": "fl",
    "georgia": "ga", "hawaii": "hi", "idaho": "id", "illinois": "il",
    "indiana": "in", "iowa": "ia", "kansas": "ks", "kentucky": "ky",
    "louisiana": "la", "maine": "me", "maryland": "md",
    "massachusetts": "ma", "michigan": "mi", "minnesota": "mn",
    "mississippi": "ms", "missouri": "mo", "montana": "mt", "nebraska": "ne",
    "nevada": "nv", "new hampshire": "nh", "new jersey": "nj",
    "new mexico": "nm", "new york": "ny", "north carolina": "nc",
    "north dakota": "nd", "ohio": "oh", "oklahoma": "ok", "oregon": "or",
    "pennsylvania": "pa", "rhode island": "ri", "south carolina": "sc",
    "south dakota": "sd", "tennessee": "tn", "texas": "tx", "utah": "ut",
    "vermont": "vt", "virginia": "va", "washington": "wa",
    "west virginia": "wv", "wisconsin": "wi", "wyoming": "wy",
}


def strip_tags(fragment: str) -> str:
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", fragment)).split())


def clean_phone(raw: str) -> str | None:
    digits = re.sub(r"\D", "", raw or "")
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    if len(digits) == 10:
        return f"{digits[:3]}-{digits[3:6]}-{digits[6:]}"
    return None


def affiliate_rows(page: str):
    """Yield (city, name, website, phone) from Local Area Affiliates tables
    (any table whose header row mentions AFFILIATE)."""
    for table in TABLE_RE.findall(page):
        rows = ROW_RE.findall(table)
        if not rows or "affiliate" not in strip_tags(rows[0]).lower():
            continue
        city = ""
        for row in rows[1:]:
            cells = CELL_RE.findall(row)
            if len(cells) < 2:
                continue
            if len(cells) == 2:  # rowspan'd city carried from previous row
                name_cell, phone_cell = cells
            else:
                city = strip_tags(cells[0])
                name_cell, phone_cell = cells[1], cells[2]
            name = strip_tags(name_cell)
            if not name:
                continue
            w = HREF_RE.search(name_cell)
            website = html.unescape(w.group(1)).strip() if w else None
            yield city, name, website, clean_phone(strip_tags(phone_cell))


def main(argv):
    force = "--force" in argv
    places = Places()
    hub = fetch(HUB, SOURCES / "orr" / "state-hub.html",
                force=force, ua=BROWSER_UA).read_text(errors="replace")
    state_urls = {}
    for path, label in OPTION_RE.findall(hub):
        st = STATE_NAMES.get(strip_tags(label).lower())
        if st:
            state_urls[st] = "https://acf.gov" + path
    if len(state_urls) < 40:
        raise SystemExit(f"orr: only {len(state_urls)} state links on the "
                         "hub page — layout changed")

    source_id = write_source(
        "acf", "orr-state-affiliates",
        kind="directory", publisher="ACF Office of Refugee Resettlement",
        title="ORR Find Resources and Contacts in Your State — "
              "local affiliate listings (per-state pages)",
        url=HUB, tier="primary",
        notes="Each state page carries its own 'current as of' date; "
              "listings are the resettlement agency local affiliates "
              "serving that state.",
    )

    records, seen, broken = [], set(), []
    for st in sorted(state_urls):
        try:
            page = fetch(state_urls[st], SOURCES / "orr" / f"state-{st}.html",
                         force=force, ua=BROWSER_UA).read_text(errors="replace")
        except SystemExit as e:
            broken.append(st)
            print(f"orr: {st} page BROKEN upstream — skipped ({e})")
            continue
        n = 0
        for city, name, website, phone in affiliate_rows(page):
            key = (st, norm(name), norm(city))
            if key in seen:
                continue
            seen.add(key)
            rec = {
                "_state": st, "_place_slug": "", "_name": name,
                "categories": ["family-support"],
                "description": "Refugee resettlement agency — local "
                               "affiliate listed in the ORR state directory.",
            }
            if city:
                rec["address"] = Flow(city=city, state=st)
                rec["service_area"] = Flow(kind="place", name=city, state=st)
                geoid, _ = places.resolve(st, city)
                if geoid:
                    rec["place"] = geoid
            else:
                rec["service_area"] = Flow(kind="state", state=st)
            if website:
                rec["website"] = website
            if phone:
                rec["phone"] = phone
            rec["sources"] = [source_id]
            rec["verified"] = Flow(on=today(), method="scrape")
            records.append(rec)
            n += 1
        print(f"orr {st}: {n} affiliates")
        if n == 0:
            broken.append(st)
            print(f"orr: {st} page had no affiliate table — reported")
    if len(broken) > 3:
        raise SystemExit(f"orr: {len(broken)} states broken/empty "
                         f"({', '.join(broken)}) — aborting, existing "
                         "records kept")
    if len(records) < 200:
        raise SystemExit(f"orr: only {len(records)} affiliates — floor is 200")
    replace_records("orgs", source_id, records)


if __name__ == "__main__":
    main(sys.argv[1:])
