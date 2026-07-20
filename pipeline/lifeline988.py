"""988 Lifeline network crisis centers -> org records (crisis / crisis-hotline).

The crisis-centers-by-state page is fully server-rendered: one WordPress
accordion item per state/territory (accordion__item-title-text) whose body is a
plain <ul> of centers — `<a href=WEBSITE>Name</a> (City, ST ZIP)`. Cloudflare
fronts the site but a browser User-Agent (util.BROWSER_UA) is accepted; no
headless browser needed. Raw page cached under sources/988lifeline/.

Quirks: a couple of centers have no link (name only); territory entries spell
the state out ("Tamuning, Guam 96913"); one entry carries trailing prose after
the location paren; two centers serve two states and appear under both (kept
once, first occurrence wins). Records shard under the *address* state.

Also emits a small static set of national crisis lines (988 itself, Crisis
Text Line, Veterans Crisis Line, Trevor Project, Trans Lifeline, LGBT National
Hotline, National DV Hotline, RAINN) — stable well-known facts, attributed to
the same source record.

Usage: python3 -m pipeline.lifeline988 [--force]
"""
import html
import re
import sys

from .emit import Places, norm, replace_records, today, write_source
from .util import BROWSER_UA, Flow, SOURCES, fetch

URL = ("https://988lifeline.org/learn/our-crisis-centers/"
       "crisis-centers-by-state-and-u-s-territory/")

ITEM_RE = re.compile(
    r'accordion__item-title-text">([^<]+)</span>(.*?)<!-- end accordion-item -->',
    re.S)
LI_RE = re.compile(r"<li>(.*?)</li>", re.S)
HREF_RE = re.compile(r'<a\s[^>]*href="([^"]+)"[^>]*>(.*?)</a>', re.S)
# "City, ST 12345" | "City, ST" | "City, Guam 96913" — inside parens
LOC_RE = re.compile(r"^(?P<city>.+?),\s*(?P<st>[A-Za-z][A-Za-z .]*?),?"
                    r"(?:\s+(?P<zip>\d{5})(-\d{4})?)?$")

TERRITORY_CODES = {
    "guam": "gu", "puerto rico": "pr", "northern mariana islands": "mp",
    "american samoa": "as", "virgin islands": "vi", "u.s. virgin islands": "vi",
}


def strip_tags(fragment: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", "", fragment)).replace("\xa0", " ").strip()


def state_code(label: str) -> str | None:
    label = label.strip()
    if re.fullmatch(r"[A-Z]{2}", label):
        return label.lower()
    return TERRITORY_CODES.get(label.lower())


def parse_location(text: str) -> dict:
    """First parenthesized 'City, ST [ZIP]' in the li text -> address dict."""
    for group in re.findall(r"\(([^()]+)\)", text):
        m = LOC_RE.match(group.strip())
        if not m:
            continue
        st = state_code(m["st"])
        if not st:
            continue
        addr = {"city": m["city"].strip(), "state": st}
        if m["zip"]:
            addr["zip"] = m["zip"]
        return addr
    return {}


def parse_website(li: str) -> str | None:
    m = HREF_RE.search(li)
    if not m:
        return None
    url = html.unescape(m.group(1)).strip()
    if not url or url.startswith(("mailto:", "tel:", "#")):
        return None
    if not re.match(r"https?://", url, re.I):
        url = "https://" + url
    return url


def parse_name(li: str) -> str:
    m = HREF_RE.search(li)
    text = strip_tags(m.group(2)) if m else strip_tags(li)
    text = re.sub(r"\s*\([^()]*\).*$", "", text)  # unlinked entries: drop location
    return text.strip(" .,–-")


# ---- static national crisis lines (well-known facts, kept current by hand) ----

def national(slug, name, cats, website, **fields):
    return {
        "_state": "us", "_place_slug": "", "_name": name,
        "id": f"us/{slug}",
        "categories": cats,
        **fields,
        "website": website,
        "service_area": Flow(kind="national"),
    }


NATIONAL_LINES = [
    national("988-lifeline", "988 Suicide & Crisis Lifeline",
             ["crisis", "crisis-hotline", "suicide-prevention"],
             "https://988lifeline.org", phone="988",
             description="Call or text 988; chat at 988lifeline.org."),
    national("crisis-text-line", "Crisis Text Line",
             ["crisis", "crisis-hotline"],
             "https://www.crisistextline.org",
             description="Text HOME to 741741"),
    national("veterans-crisis-line", "Veterans Crisis Line",
             ["crisis", "crisis-hotline", "veterans"],
             "https://www.veteranscrisisline.net", phone="988",
             description="Call 988 and press 1, or text 838255."),
    national("trevor-project", "The Trevor Project",
             ["crisis", "lgbtq"],
             "https://www.thetrevorproject.org", phone="866-488-7386",
             description="Crisis support for LGBTQ+ young people."),
    national("trans-lifeline", "Trans Lifeline",
             ["crisis", "trans-services", "lgbtq"],
             "https://translifeline.org", phone="877-565-8860",
             description="Peer support hotline run by and for trans people."),
    national("lgbt-national-hotline", "LGBT National Hotline",
             ["crisis", "lgbtq"],
             "https://lgbthotline.org", phone="888-843-4564"),
    national("national-domestic-violence-hotline", "National Domestic Violence Hotline",
             ["domestic-violence", "crisis-hotline"],
             "https://www.thehotline.org", phone="800-799-7233",
             description="Call 800-799-7233, text START to 88788."),
    national("national-sexual-assault-hotline",
             "National Sexual Assault Hotline (RAINN)",
             ["sexual-assault", "crisis-hotline"],
             "https://rainn.org", phone="800-656-4673"),
]


def main(argv):
    force = "--force" in argv
    places = Places()
    cache = SOURCES / "988lifeline" / "crisis-centers.html"
    page = fetch(URL, cache, force=force, ua=BROWSER_UA).read_text(errors="replace")

    items = ITEM_RE.findall(page)
    if len(items) < 50:
        raise SystemExit(f"lifeline988: only {len(items)} state accordions — "
                         "page layout changed?")

    source_id = write_source(
        "988lifeline", "crisis-centers",
        kind="directory", publisher="988 Suicide & Crisis Lifeline",
        title="Crisis Centers by State and U.S. Territory",
        url=URL, tier="primary",
    )

    records, seen = [], set()
    for state_label, body in items:
        fallback = state_code(state_label) or TERRITORY_CODES.get(
            state_label.strip().lower())
        for li in LI_RE.findall(body):
            name = parse_name(li)
            if not name:
                continue
            addr = parse_location(strip_tags(li))
            st = addr.get("state") or fallback
            if not st:
                continue
            key = (norm(name), norm(addr.get("city", "")))
            if key in seen:  # same center listed under a second state it serves
                continue
            seen.add(key)
            rec = {
                "_state": st, "_place_slug": "", "_name": name,
                "categories": ["crisis", "crisis-hotline"],
            }
            if addr:
                rec["address"] = Flow(addr)
                geoid, _ = places.resolve(st, addr["city"])
                if geoid:
                    rec["place"] = geoid
            website = parse_website(li)
            if website:
                rec["website"] = website
            rec["sources"] = [source_id]
            rec["verified"] = Flow(on=today(), method="scrape")
            records.append(rec)

    if len(records) < 150:
        raise SystemExit(f"lifeline988: only {len(records)} centers — expected ~200")
    print(f"parsed {len(records)} network crisis centers from {len(items)} states")

    for rec in NATIONAL_LINES:
        rec = dict(rec)
        rec["sources"] = [source_id]
        rec["verified"] = Flow(on=today(), method="scrape")
        records.append(rec)

    replace_records("orgs", source_id, records)


if __name__ == "__main__":
    main(sys.argv[1:])
