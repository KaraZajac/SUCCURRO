"""National Empowerment Center peer respite directory -> org records.

peerrespite.com's directory is gone (404), so the source is NEC's Directory
of Peer Respites (power2u.org) — ~35 peer-run, voluntary crisis-alternative
houses. One page: <h4> tokens in document order are either a state heading
(text is a US state name) or a respite name; each entry's first following
<p> is an info block of Website/Location/Phone/Email lines separated by
<br/>. The long program descriptions that follow are NEC/program prose and
are never copied — every record gets the same one-line factual description.
Footer h4s (SUPPORT US, Contact Info, ...) carry no info block and drop out.

ToS check 2026-07-21: power2u.org robots.txt allows the page; its
Terms & Conditions cover only store shipping/returns — no content-reuse
restrictions. Facts-only re-expression, attributed (DATA-RIGHTS.md).

Usage: python3 -m pipeline.peerrespites [--force]
"""
import html
import re
import sys

from .emit import Places, replace_records, today, write_source
from .util import Flow, SOURCES, fetch

URL = "https://power2u.org/directory-of-peer-respites/"

H4_RE = re.compile(r"<h4[^>]*>(.*?)</h4>", re.S)
P_RE = re.compile(r"<p[^>]*>(.*?)</p>", re.S)
HREF_RE = re.compile(r'href="(https?://[^"]+)"')
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
PHONE_RE = re.compile(r"\(?\b(\d{3})\)?[-. ]\s*(\d{3})[-. ](\d{4})\b")

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
US_STATE_CODES = set(STATE_NAMES.values())

DESCRIPTION = "Peer respite — voluntary, peer-run crisis alternative."


def strip_tags(fragment: str) -> str:
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", fragment)).split())


def parse_location(raw: str) -> tuple[str | None, str | None]:
    """'Santa Cruz, CA' / 'Keene, New Hampshire' -> (city, state); a
    multi-county service blurb yields (None, state)."""
    parts = [p.strip() for p in raw.split(",") if p.strip()]
    if not parts:
        return None, None
    tail = parts[-1].rstrip(".").lower()
    st = tail if tail in US_STATE_CODES and len(tail) == 2 \
        else STATE_NAMES.get(tail)
    if not st:
        return None, None
    if len(parts) == 2 and "count" not in parts[0].lower():
        return parts[0], st
    return None, st


def info_block(body: str) -> str | None:
    """First <p> of the entry that reads as a contact block."""
    for p in P_RE.findall(body):
        text = strip_tags(p)
        if re.search(r"\b(Location|Phone|Website|Email)\s*:", text):
            return p
    return None


def main(argv):
    force = "--force" in argv
    places = Places()
    page = fetch(URL, SOURCES / "power2u" / "peer-respite-directory.html",
                 force=force).read_text(errors="replace")

    source_id = write_source(
        "power2u", "peer-respite-directory",
        kind="directory", publisher="National Empowerment Center",
        title="NEC Directory of Peer Respites",
        url=URL, tier="secondary",
    )

    tokens = [(m.start(), m.end(), m.group(1)) for m in H4_RE.finditer(page)]
    records, heading_st, skipped = [], "", 0
    for i, (start, end, raw) in enumerate(tokens):
        text = strip_tags(raw)
        st_hit = STATE_NAMES.get(text.lower())
        if st_hit:
            heading_st = st_hit
            continue
        body = page[end:tokens[i + 1][0] if i + 1 < len(tokens) else len(page)]
        block = info_block(body)
        if not block or not text:
            skipped += 1  # footer/nav h4s land here
            continue
        # drop a "Serving <counties>" tail folded into the heading
        name = re.sub(r"\s+Serving\s.+$", "", text).strip()
        lines = [strip_tags(ln) for ln in re.split(r"<br\s*/?>", block)]
        city = state = None
        for ln in lines:
            m = re.match(r"Location:\s*(.+)$", ln, re.I)
            if m:
                city, state = parse_location(m.group(1))
        state = state or heading_st
        if not state:
            print(f"peerrespites: no state for {name!r} — skipped")
            continue
        rec = {
            "_state": state, "_place_slug": "", "_name": name,
            "categories": ["mental-health", "peer-support"],
            "description": DESCRIPTION,
        }
        if city:
            rec["address"] = Flow(city=city, state=state)
            geoid, _ = places.resolve(state, city)
            if geoid:
                rec["place"] = geoid
        w = HREF_RE.search(block)
        if w:
            rec["website"] = html.unescape(w.group(1)).strip()
        pm = PHONE_RE.search(strip_tags(block))
        if pm:
            rec["phone"] = f"{pm.group(1)}-{pm.group(2)}-{pm.group(3)}"
        em = EMAIL_RE.search(strip_tags(block))
        if em:
            rec["email"] = em.group(0)
        rec["sources"] = [source_id]
        rec["verified"] = Flow(on=today(), method="scrape")
        records.append(rec)

    print(f"peerrespites: {len(records)} respites "
          f"({skipped} non-entry h4 tokens ignored)")
    if len(records) < 25:
        raise SystemExit(f"peerrespites: only {len(records)} respites — "
                         "floor is 25")
    replace_records("orgs", source_id, records)


if __name__ == "__main__":
    main(sys.argv[1:])
