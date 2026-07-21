"""ACF FYSB Runaway & Homeless Youth grantees -> org records.

Per-state pages https://acf.gov/fysb/grants/<state>-rhy list each grantee
as org name + city/state + website (+ sometimes phone/email) with no
street address — an org record, not a site. The state-page slugs are
crawled from the FYSB grantee map page (60 jurisdictions incl. DC and
the territories/freely-associated states). acf.gov's WAF challenges
non-browser clients, so fetches use BROWSER_UA; pages cache under
sources/rhy/. Federal public domain.

Program sections per page (h3 anchors): Basic Center (emergency youth
shelter), Maternity Group Home, Transitional Living, Prevention
Demonstration, Street Outreach, and Support Systems for Rural Homeless
Youth. Orgs appearing under several programs are merged with all
programs listed in the description; housing-program grantees (BCP/MGH/
TLP) get ["youth-shelter", "family-youth"], outreach/prevention-only
grantees ["family-youth"]. A d.b.a. duplicate (same state + website
host + city, one name a prefix of the other) is merged into the fuller
name.

Usage: python3 -m pipeline.rhy [--force]
"""
import html
import re
import sys
from urllib.parse import urlsplit

from .emit import norm, replace_records, today, write_source
from .util import BROWSER_UA, Flow, SOURCES, fetch

MAP_URL = "https://acf.gov/fysb/map/grantees-family-and-youth-services-bureau"

# slug (from /fysb/grants/<slug>-rhy) -> USPS code
STATE_SLUGS = {
    "alabama": "al", "alaska": "ak", "american-samoa": "as", "arizona": "az",
    "arkansas": "ar", "california": "ca", "colorado": "co",
    "connecticut": "ct", "delaware": "de", "district-of-columbia": "dc",
    "florida": "fl", "georgia": "ga", "guam": "gu", "hawaii": "hi",
    "idaho": "id", "illinois": "il", "indiana": "in", "iowa": "ia",
    "kansas": "ks", "kentucky": "ky", "louisiana": "la", "maine": "me",
    "mariana": "mp", "marshall-islands": "mh", "maryland": "md",
    "massachusetts": "ma", "michigan": "mi", "micronesia": "fm",
    "minnesota": "mn", "mississippi": "ms", "missouri": "mo",
    "montana": "mt", "nebraska": "ne", "nevada": "nv",
    "new-hampshire": "nh", "new-jersey": "nj", "new-mexico": "nm",
    "new-york": "ny", "north-carolina": "nc", "north-dakota": "nd",
    "ohio": "oh", "oklahoma": "ok", "oregon": "or", "palau": "pw",
    "pennsylvania": "pa", "puerto-rico": "pr", "rhode-island": "ri",
    "south-carolina": "sc", "south-dakota": "sd", "tennessee": "tn",
    "texas": "tx", "utah": "ut", "vermont": "vt", "virginia": "va",
    "virgin-islands": "vi", "washington": "wa", "west-virginia": "wv",
    "wisconsin": "wi", "wyoming": "wy",
}

# (heading fragment, program label for descriptions, housing program?)
PROGRAMS = [
    ("basic center", "Basic Center Program (emergency youth shelter)", True),
    ("maternity group home",
     "Maternity Group Home Program (housing for pregnant and parenting "
     "youth)", True),
    ("transitional living",
     "Transitional Living Program (longer-term housing for older homeless "
     "youth)", True),
    ("prevention demonstration",
     "Prevention Demonstration Program (youth homelessness prevention)",
     False),
    ("street outreach",
     "Street Outreach Program (street-based outreach to youth)", False),
    ("rural homeless", "Support Systems for Rural Homeless Youth", False),
]

CITY_ST_RE = re.compile(r"^(.{2,60}?),\s*([A-Z]{2})\.?\s*$")
PHONE_RE = re.compile(r"\(?\b(\d{3})\)?[-. ]\s*(\d{3})[-. ](\d{4})\b")
EMAIL_RE = re.compile(r"^[\w.+-]+@[\w-]+(\.[\w-]+)+$")
SKIP_NAME_RE = re.compile(r"grant period|none at this time|^\W*$", re.I)


def phone_fmt(text: str) -> str | None:
    m = PHONE_RE.search(text or "")
    return f"{m.group(1)}-{m.group(2)}-{m.group(3)}" if m else None


def section_lines(body: str) -> list[str]:
    """Flatten a program section to text lines; grantee names (the
    <strong> heads) are marked with a leading \\x00, anchors become
    their href so websites survive tag stripping."""
    body = re.sub(r'<a[^>]+href="(https?://[^"]+)"[^>]*>.*?</a>',
                  "\n\\1\n", body, flags=re.S)
    body = re.sub(r"<strong>\s*(.*?)\s*</strong>", "\n\x00\\1\n", body,
                  flags=re.S)
    body = re.sub(r"</?(?:p|br|h4|div|ul|li)[^>]*/?>", "\n", body)
    text = html.unescape(re.sub(r"<[^>]+>", " ", body))
    return [ln for ln in (" ".join(l.split()) for l in text.splitlines())
            if ln]


def parse_state(page: str, st: str) -> list[dict]:
    """One dict per (grantee, program) occurrence on a state page."""
    main = page[page.find("<main"):page.find("</main>")]
    main = re.sub(r"<svg.*?</svg>", "", main, flags=re.S)
    entries = []
    parts = re.split(r"<h3[^>]*>(.*?)</h3>", main, flags=re.S)
    for head, body in zip(parts[1::2], parts[2::2]):
        title = html.unescape(re.sub(r"<[^>]+>", " ", head)).lower()
        hits = [p for p in PROGRAMS if p[0] in title]
        if len(hits) != 1:
            continue  # the in-page nav h3 lists every program; skip it
        _, label, housing = hits[0]
        entry = None
        for ln in section_lines(body):
            if ln.startswith("\x00"):
                name = ln[1:].strip()
                if SKIP_NAME_RE.search(name):
                    entry = None
                    continue
                entry = {"st": st, "name": name, "programs": [label],
                         "housing": housing, "city": None, "phone": None,
                         "email": None, "website": None}
                entries.append(entry)
                continue
            if entry is None:
                continue
            if ln.lower().startswith(("http://", "https://")):
                entry["website"] = entry["website"] or ln
                continue
            m = CITY_ST_RE.match(ln)
            if m and not any(ch.isdigit() for ch in m.group(1)):
                entry["city"] = entry["city"] or m.group(1).strip()
                continue
            if re.match(r"phone\b", ln, re.I) or (PHONE_RE.search(ln)
                                                  and "@" not in ln):
                entry["phone"] = entry["phone"] or phone_fmt(ln)
                continue
            if EMAIL_RE.match(ln) and not re.match(r"^\w+\.\w+@", ln):
                entry["email"] = entry["email"] or ln.lower()
    return entries


def host_of(url: str | None) -> str:
    if not url:
        return ""
    return urlsplit(url).netloc.lower().removeprefix("www.")


def merge_entries(entries: list[dict]) -> list[dict]:
    """Merge program occurrences by (state, normalized name), then fold
    d.b.a. name variants (same state+host+city, prefix names)."""
    by_key: dict[tuple, dict] = {}
    for e in entries:
        key = (e["st"], norm(e["name"]))
        prev = by_key.get(key)
        if not prev:
            by_key[key] = e
            continue
        for p in e["programs"]:
            if p not in prev["programs"]:
                prev["programs"].append(p)
        prev["housing"] = prev["housing"] or e["housing"]
        for f in ("city", "phone", "email", "website"):
            prev[f] = prev[f] or e[f]

    merged = list(by_key.values())
    by_host: dict[tuple, dict] = {}
    out = []
    for e in sorted(merged, key=lambda e: -len(e["name"])):
        hk = (e["st"], host_of(e["website"]), norm(e["city"] or ""))
        prev = by_host.get(hk) if hk[1] else None
        if prev and norm(prev["name"]).startswith(norm(e["name"])):
            for p in e["programs"]:  # e's name is a prefix of prev's
                if p not in prev["programs"]:
                    prev["programs"].append(p)
            prev["housing"] = prev["housing"] or e["housing"]
            for f in ("city", "phone", "email"):
                prev[f] = prev[f] or e[f]
            print(f"{e['st']}: merged {e['name']!r} into {prev['name']!r}")
            continue
        if hk[1]:
            by_host[hk] = e
        out.append(e)
    return out


def to_record(e: dict, source_id: str) -> dict:
    cats = (["youth-shelter", "family-youth"] if e["housing"]
            else ["family-youth"])
    desc = ("Runaway and Homeless Youth grantee of the HHS Family and "
            "Youth Services Bureau. Programs: "
            + "; ".join(e["programs"]) + ".")
    rec = {"_state": e["st"], "_place_slug": "", "_name": e["name"],
           "categories": cats, "description": desc}
    if e["city"]:
        rec["address"] = Flow(city=e["city"], state=e["st"])
    if e["phone"]:
        rec["phone"] = e["phone"]
    if e["email"]:
        rec["email"] = e["email"]
    if e["website"]:
        rec["website"] = e["website"]
    rec["sources"] = [source_id]
    rec["verified"] = Flow(on=today(), method="scrape")
    return rec


def main(argv):
    force = "--force" in argv
    index = fetch(MAP_URL, SOURCES / "rhy" / "grantee-map.html",
                  force=force, ua=BROWSER_UA).read_text(errors="replace")
    slugs = sorted(set(re.findall(r'href="/fysb/grants/([a-z-]+)-rhy"',
                                  index)))
    unknown = [s for s in slugs if s not in STATE_SLUGS]
    if unknown:
        raise SystemExit(f"rhy: unmapped state slugs {unknown}")
    if len(slugs) < 55:
        raise SystemExit(f"rhy: only {len(slugs)} state links on the map "
                         "page — layout changed")

    source_id = write_source(
        "acf", "fysb-rhy-grantees", kind="directory",
        publisher="ACF Family and Youth Services Bureau",
        title="Runaway and Homeless Youth grantees (per-state pages)",
        url=MAP_URL, tier="primary")

    entries = []
    for slug in slugs:
        st = STATE_SLUGS[slug]
        page = fetch(f"https://acf.gov/fysb/grants/{slug}-rhy",
                     SOURCES / "rhy" / f"{slug}.html",
                     force=force, ua=BROWSER_UA).read_text(errors="replace")
        found = parse_state(page, st)
        print(f"rhy {st}: {len(found)} grantee listings")
        entries.extend(found)

    records = [to_record(e, source_id) for e in merge_entries(entries)]
    if len(records) < 250:
        raise SystemExit(f"rhy: only {len(records)} grantee orgs — "
                         "floor is 250")
    replace_records("orgs", source_id, records)


if __name__ == "__main__":
    main(sys.argv[1:])
