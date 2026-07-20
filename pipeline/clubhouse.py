"""Clubhouse International directory -> US clubhouse org records (mental-health).

The international directory is server-rendered per starting letter (?fl=A..Z).
Each entry is a nested div: optional linked name, <br />-separated street lines
ending in "City, State, USA <zip>" (non-US entries carry their own country and
are filtered out), then Director/Phone/Fax/Email/Website Address labels.
Emails are Cloudflare-obfuscated (data-cfemail XOR) and decoded here. Letter
pages cached under sources/clubhouse-intl/.

Usage: python3 -m pipeline.clubhouse [--force]
"""
import html
import re
import string
import sys

from .emit import Places, replace_records, today, write_source
from .util import Flow, SOURCES, fetch

URL = "https://clubhouse-intl.org/what-we-do/international-directory/?fl={letter}"

US_LINE_RE = re.compile(r"^(?P<city>.+?),\s*(?P<state>[A-Za-z. ]+?),\s*USA\.?\s*(?P<zip>\d{5})?(-\d{4})?\s*$")
WEBSITE_RE = re.compile(r'Website Address:</strong>\s*<a[^>]*href="([^"]+)"')
NAME_LINK_RE = re.compile(r'<a target="_blank" href="([^"]+)"')
CFEMAIL_RE = re.compile(r'data-cfemail="([0-9a-f]+)"')
PHONE_RE = re.compile(r"Phone:\s*(.+)")

STATE_CODES = {
    "alabama": "al", "alaska": "ak", "arizona": "az", "arkansas": "ar",
    "california": "ca", "colorado": "co", "connecticut": "ct", "delaware": "de",
    "district of columbia": "dc", "florida": "fl", "georgia": "ga", "hawaii": "hi",
    "idaho": "id", "illinois": "il", "indiana": "in", "iowa": "ia", "kansas": "ks",
    "kentucky": "ky", "louisiana": "la", "maine": "me", "maryland": "md",
    "massachusetts": "ma", "michigan": "mi", "minnesota": "mn", "mississippi": "ms",
    "missouri": "mo", "montana": "mt", "nebraska": "ne", "nevada": "nv",
    "new hampshire": "nh", "new jersey": "nj", "new mexico": "nm", "new york": "ny",
    "north carolina": "nc", "north dakota": "nd", "ohio": "oh", "oklahoma": "ok",
    "oregon": "or", "pennsylvania": "pa", "puerto rico": "pr", "rhode island": "ri",
    "south carolina": "sc", "south dakota": "sd", "tennessee": "tn", "texas": "tx",
    "utah": "ut", "vermont": "vt", "virginia": "va", "washington": "wa",
    "west virginia": "wv", "wisconsin": "wi", "wyoming": "wy",
}


def decode_cfemail(hexstr: str) -> str:
    data = bytes.fromhex(hexstr)
    return "".join(chr(b ^ data[0]) for b in data[1:])


def norm_phone(raw: str) -> str | None:
    m = re.search(r"\(?(\d{3})\)?[\s./-]{0,3}(\d{3})[\s./-]{0,3}(\d{4})", raw or "")
    return f"{m.group(1)}-{m.group(2)}-{m.group(3)}" if m else None


def to_text(chunk: str) -> list[str]:
    text = re.sub(r"<br\s*/?>", "\n", chunk)
    text = re.sub(r"<img[^>]*>", "", text)
    text = html.unescape(re.sub(r"<[^>]+>", "", text)).replace("\xa0", " ")
    return [" ".join(ln.split()) for ln in text.splitlines() if ln.strip()]


def parse_entry(chunk: str) -> dict | None:
    lines = to_text(chunk)
    if not lines:
        return None
    us = next((US_LINE_RE.match(ln) for ln in lines if US_LINE_RE.match(ln)), None)
    if not us:
        return None  # non-US clubhouse (or no location line)
    state = STATE_CODES.get(us["state"].strip().lower())
    if not state:
        return None
    idx = lines.index(us.group(0))
    name = lines[0]
    street = [ln for ln in lines[1:idx] if ":" not in ln]
    entry = {"name": name, "state": state, "city": us["city"].strip(), "street": street}
    if us["zip"]:
        entry["zip"] = us["zip"]
    m = WEBSITE_RE.search(chunk) or NAME_LINK_RE.search(chunk)
    if m:
        url = m.group(1).strip()
        entry["website"] = url if url.startswith("http") else f"https://{url}"
    phone_line = next((ln for ln in lines if ln.startswith("Phone:")), "")
    phone = norm_phone(PHONE_RE.sub(r"\1", phone_line)) if phone_line else None
    if phone:
        entry["phone"] = phone
    m = CFEMAIL_RE.search(chunk)
    if m:
        entry["email"] = decode_cfemail(m.group(1))
    return entry


def main(argv):
    force = "--force" in argv
    places = Places()
    source_id = write_source(
        "clubhouse-intl", "international-directory",
        kind="directory", publisher="Clubhouse International",
        title="Clubhouse International directory (US clubhouses)",
        url="https://clubhouse-intl.org/what-we-do/international-directory/",
        tier="primary",
    )

    entries, non_us = [], 0
    for letter in string.ascii_uppercase:
        cache = SOURCES / "clubhouse-intl" / f"directory-{letter}.html"
        page = fetch(URL.format(letter=letter), cache, force=force).read_text()
        i = page.find('class="clubhouse-search-results"')
        if i < 0:
            raise SystemExit(f"clubhouse: no results container on ?fl={letter} — layout changed")
        section = page[i:]
        for chunk in re.split(r"</div>\s*</div>", section):
            if "Director:" not in chunk and "Phone:" not in chunk:
                continue
            entry = parse_entry(chunk)
            if entry:
                entries.append(entry)
            else:
                non_us += 1
    print(f"parsed {len(entries)} US clubhouses ({non_us} non-US/unparsed entries skipped)")

    records = []
    for e in entries:
        addr = {"city": e["city"], "state": e["state"]}
        if e["street"]:
            addr = {"street": ", ".join(e["street"]), **addr}
        if e.get("zip"):
            addr["zip"] = e["zip"]
        geoid, _ = places.resolve(e["state"], e["city"])
        rec = {
            "_state": e["state"], "_place_slug": "", "_name": e["name"],
            "categories": ["mental-health", "peer-support"],
            "parent_org": "us/clubhouse-international",
            "address": Flow(addr),
        }
        if geoid:
            rec["place"] = geoid
        for f in ("phone", "email", "website"):
            if e.get(f):
                rec[f] = e[f]
        rec["sources"] = [source_id]
        rec["verified"] = Flow(on=today(), method="scrape")
        records.append(rec)

    records.append({
        "_state": "us", "_place_slug": "", "_name": "Clubhouse International",
        "id": "us/clubhouse-international",
        "categories": ["mental-health", "peer-support"],
        "description": "Global network of Clubhouses offering the Clubhouse model of "
                       "psychosocial rehabilitation for people living with mental illness.",
        "website": "https://clubhouse-intl.org",
        "service_area": Flow(kind="national"),
        "sources": [source_id],
        "verified": Flow(on=today(), method="scrape"),
    })

    if len(records) < 150:
        raise SystemExit(f"clubhouse: only {len(records)} records — expected 150+; aborting")
    replace_records("orgs", source_id, records)


if __name__ == "__main__":
    main(sys.argv[1:])
