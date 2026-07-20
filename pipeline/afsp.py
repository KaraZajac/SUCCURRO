"""AFSP (American Foundation for Suicide Prevention) chapters -> org records
(suicide-prevention / peer-support).

afsp.org's sitemap-0.xml lists ~334 /chapter/ URLs, but most are chapter
news/event sub-pages; only ~75 are real chapter roots. A root is identified
by its "Chapter contact" block (sub-pages have none), which carries staff
contacts as <address> entries with tel: links and Cloudflare-obfuscated
emails (data-cfemail, XOR-decoded here). The state comes from the page's
data-donor-drive-id attribute (e.g. "AL"), falling back to a state-name
match on the chapter title. Pages are throttled (util.get) and cached under
sources/afsp/pages/. The chapter zip-lookup API
(serene-dusk-44738.herokuapp.com/astro-zip-lookup) and the support-groups
API (afsp-support-groups-*.herokuapp.com) were both still 503 on
2026-07-20. Facts-only re-expression, attributed (see DATA-RIGHTS.md).

Usage: python3 -m pipeline.afsp [--force]
"""
import html
import re
import sys
from collections import Counter

from .emit import replace_records, today, write_source
from .util import Flow, SOURCES, fetch

SITEMAP = "https://afsp.org/sitemap-0.xml"
FIND_URL = "https://afsp.org/find-a-local-chapter/"

LOC_RE = re.compile(r"<loc>\s*(https://afsp\.org/chapter/[^<]+?)\s*</loc>")
TITLE_RE = re.compile(r'property="og:title" content="([^"]*)"')
CONTACT_RE = re.compile(r"Chapter contact\s*</h3>(.{0,4000}?)</section>", re.S)
ADDRESS_RE = re.compile(r"<address[^>]*>(.*?)</address>", re.S)
DONOR_RE = re.compile(r'data-donor-drive-id="([A-Za-z][A-Za-z -]*)"')
TEL_RE = re.compile(r'href="tel:([\d()+. -]{7,})"')
CFEMAIL_RE = re.compile(r'data-cfemail="([0-9a-fA-F]+)"')

STATE_NAMES = {
    "alabama": "al", "alaska": "ak", "arizona": "az", "arkansas": "ar",
    "california": "ca", "colorado": "co", "connecticut": "ct", "delaware": "de",
    "district of columbia": "dc", "florida": "fl", "georgia": "ga",
    "hawaii": "hi", "idaho": "id", "illinois": "il", "indiana": "in",
    "iowa": "ia", "kansas": "ks", "kentucky": "ky", "louisiana": "la",
    "maine": "me", "maryland": "md", "massachusetts": "ma", "michigan": "mi",
    "minnesota": "mn", "mississippi": "ms", "missouri": "mo", "montana": "mt",
    "nebraska": "ne", "nevada": "nv", "new hampshire": "nh", "new jersey": "nj",
    "new mexico": "nm", "new york": "ny", "north carolina": "nc",
    "north dakota": "nd", "ohio": "oh", "oklahoma": "ok", "oregon": "or",
    "pennsylvania": "pa", "rhode island": "ri", "south carolina": "sc",
    "south dakota": "sd", "tennessee": "tn", "texas": "tx", "utah": "ut",
    "vermont": "vt", "virginia": "va", "washington": "wa",
    "west virginia": "wv", "wisconsin": "wi", "wyoming": "wy",
    "puerto rico": "pr",
}
US_STATE_CODES = set(STATE_NAMES.values()) | {"dc"}


def decode_cfemail(hexstr: str) -> str:
    data = bytes.fromhex(hexstr)
    return "".join(chr(b ^ data[0]) for b in data[1:])


def clean_phone(raw: str) -> str | None:
    digits = re.sub(r"\D", "", raw or "")
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    if len(digits) != 10:
        return None
    return f"{digits[:3]}-{digits[3:6]}-{digits[6:]}"


def find_state(title: str) -> str:
    """Longest state name mentioned in the chapter title wins."""
    low = " " + re.sub(r"[^a-z ]+", " ", title.lower()) + " "
    low = " " + " ".join(low.split()) + " "
    best = ""
    for name, code in STATE_NAMES.items():
        if f" {name} " in low and len(name) > len(best):
            best, best_code = name, code
    return best_code if best else ""


def main(argv):
    force = "--force" in argv
    sitemap = fetch(SITEMAP, SOURCES / "afsp" / "sitemap-0.xml",
                    force=force).read_text()
    urls = sorted(set(LOC_RE.findall(sitemap)))
    if len(urls) < 200:
        raise SystemExit(f"afsp: only {len(urls)} /chapter/ sitemap URLs — "
                         "expected ~334")

    source_id = write_source(
        "afsp", "chapter-directory",
        kind="directory", publisher="American Foundation for Suicide Prevention",
        title="AFSP chapter pages (sitemap-0.xml crawl)",
        url=FIND_URL, tier="primary",
    )

    records, skipped, got = [], Counter(), Counter()
    for url in urls:
        slug = url.rstrip("/").rsplit("/", 1)[-1]
        page = fetch(url, SOURCES / "afsp" / "pages" / f"{slug}.html",
                     force=force).read_text(errors="replace")
        cm = CONTACT_RE.search(page)
        if not cm:
            skipped["sub-page"] += 1  # news/event sub-page, not a chapter root
            continue
        tm = TITLE_RE.search(page)
        title = html.unescape(tm.group(1)).strip() if tm else ""
        if not title:
            skipped["no-title"] += 1
            print(f"afsp: skip {slug} — chapter root without og:title")
            continue
        name = title if title.lower().startswith("afsp") else f"AFSP {title}"

        st, donor_id = "", ""
        dm = DONOR_RE.search(page)
        if dm:
            donor_id = dm.group(1)
            head = re.split(r"[ -]", donor_id)[0].lower()
            if head in US_STATE_CODES:
                st = head
        if not st:
            st = find_state(title)
        if not st:
            skipped["no-state"] += 1
            print(f"afsp: skip {slug} — no state derivable ({title!r})")
            continue

        rec = {
            "_state": st, "_place_slug": "", "_name": name,
            "categories": ["suicide-prevention", "peer-support"],
            "parent_org": "us/afsp",
            "website": url,
        }
        if title.lower() in STATE_NAMES and STATE_NAMES[title.lower()] == st:
            rec["service_area"] = Flow(kind="state", state=st)
        block = cm.group(1)
        pm = TEL_RE.search(block)
        phone = clean_phone(pm.group(1)) if pm else None
        if phone:
            rec["phone"] = phone
            got["phone"] += 1
        em = CFEMAIL_RE.search(block)
        if em:
            rec["email"] = decode_cfemail(em.group(1))
            got["email"] += 1
        external_ids = Flow(afsp_chapter_page=url)
        if donor_id:
            external_ids["donor_drive"] = donor_id
        rec["external_ids"] = external_ids
        rec["sources"] = [source_id]
        rec["verified"] = Flow(on=today(), method="scrape")
        records.append(rec)

    if skipped:
        print("skipped:", dict(skipped))
    for field in ("phone", "email"):
        print(f"enriched {got[field]}/{len(records)} chapters with {field}")
    if len(records) < 50:
        raise SystemExit(f"afsp: only {len(records)} chapter roots — expected ~75")

    records.append({
        "_state": "us", "_place_slug": "",
        "_name": "American Foundation for Suicide Prevention",
        "id": "us/afsp",
        "aliases": ["AFSP"],
        "categories": ["suicide-prevention"],
        "description": "National suicide-prevention organization — local "
                       "chapters run education programs, advocacy, "
                       "Out of the Darkness walks, and loss-survivor "
                       "support programs.",
        "website": "https://afsp.org",
        "service_area": Flow(kind="national"),
        "sources": [source_id],
        "verified": Flow(on=today(), method="scrape"),
    })

    replace_records("orgs", source_id, records)


if __name__ == "__main__":
    main(sys.argv[1:])
