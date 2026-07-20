"""The Arc chapter directory -> org records (people with intellectual and
developmental disabilities and their families; family-support).

thearc.org publishes a dedicated chapter sitemap (~578 chapter pages). Each
chapter page carries a uniform Contact textblock —
`<h2>Contact</h2><p>NAME</p><p>ADDRESS</p><p>Phone: ...</p>` — plus a
VISIT WEBSITE button (href often empty). The crawl is throttled (util.get)
and cached under sources/thearc/pages/; a page whose Contact block is
missing or unparseable is skipped and reported, not fatal. Facts-only
re-expression, attributed (see DATA-RIGHTS.md).

Usage: python3 -m pipeline.thearc [--force]
"""
import html
import re
import sys
from collections import Counter

from .emit import Places, replace_records, today, write_source
from .util import Flow, SOURCES, fetch

SITEMAP = "https://thearc.org/chapter-sitemap.xml"
FIND_URL = "https://thearc.org/find-a-chapter/"

LOC_RE = re.compile(r"<loc>\s*(https://thearc\.org/chapter/[^<]+?)\s*</loc>")
CONTACT_RE = re.compile(r"<h2>\s*Contact\s*</h2>(.{0,3000}?)(?:</section>|<h2)", re.S)
P_RE = re.compile(r"<p[^>]*>(.*?)</p>", re.S)
WEBSITE_RE = re.compile(
    r'<a[^>]+href="([^"]+)"[^>]*class="avia-button[^"]*"[^>]*>\s*'
    r"<span[^>]*>\s*VISIT WEBSITE", re.S)
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
TAIL_RE = re.compile(r"^([A-Za-z]{2})\.?\s*(\d{5})?(-\d{4})?$")

US_STATE_CODES = {
    "al", "ak", "az", "ar", "ca", "co", "ct", "de", "dc", "fl", "ga", "hi",
    "id", "il", "in", "ia", "ks", "ky", "la", "me", "md", "ma", "mi", "mn",
    "ms", "mo", "mt", "ne", "nv", "nh", "nj", "nm", "ny", "nc", "nd", "oh",
    "ok", "or", "pa", "pr", "ri", "sc", "sd", "tn", "tx", "ut", "vt", "va",
    "vi", "wa", "wv", "wi", "wy", "gu", "mp", "as",
}


def strip_tags(fragment: str) -> str:
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", fragment)).split())


def parse_address(raw: str) -> dict:
    """'641 Fairview Avenue North, Suite 195, Saint Paul, MN 55104' ->
    {street, city, state, zip}; {} when no trailing US state resolves."""
    parts = [p.strip() for p in raw.split(",") if p.strip()]
    if len(parts) < 2:
        return {}
    m = TAIL_RE.match(parts[-1])
    if not m or m.group(1).lower() not in US_STATE_CODES:
        return {}
    addr = {"city": parts[-2], "state": m.group(1).lower()}
    if m.group(2):
        addr["zip"] = m.group(2) + (m.group(3) or "")
    if len(parts) > 2:
        addr = {"street": ", ".join(parts[:-2]), **addr}
    return addr


def clean_phone(raw: str) -> str | None:
    digits = re.sub(r"\D", "", raw or "")
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    if len(digits) != 10:
        return None
    return f"{digits[:3]}-{digits[3:6]}-{digits[6:]}"


def main(argv):
    force = "--force" in argv
    places = Places()
    sitemap = fetch(SITEMAP, SOURCES / "thearc" / "chapter-sitemap.xml",
                    force=force).read_text()
    urls = sorted(set(LOC_RE.findall(sitemap)))
    if len(urls) < 400:
        raise SystemExit(f"thearc: only {len(urls)} sitemap URLs — expected ~578")

    source_id = write_source(
        "thearc", "chapter-directory",
        kind="directory", publisher="The Arc of the United States",
        title="The Arc chapter pages (chapter-sitemap.xml crawl)",
        url=FIND_URL, tier="primary",
    )

    records, skipped, got = [], Counter(), Counter()
    for url in urls:
        slug = url.rstrip("/").rsplit("/", 1)[-1]
        page = fetch(url, SOURCES / "thearc" / "pages" / f"{slug}.html",
                     force=force).read_text(errors="replace")
        m = CONTACT_RE.search(page)
        if not m:
            skipped["no-contact-block"] += 1
            print(f"thearc: skip {slug} — no Contact block")
            continue
        paras = [strip_tags(p) for p in P_RE.findall(m.group(1))]
        paras = [p for p in paras if p]
        if not paras:
            skipped["empty-contact-block"] += 1
            print(f"thearc: skip {slug} — empty Contact block")
            continue
        name = paras[0]
        addr, phone = {}, None
        for p in paras[1:]:
            if p.lower().startswith("phone"):
                phone = clean_phone(p)
            elif not addr:
                addr = parse_address(p)
        st = addr.get("state")
        if not st:
            skipped["no-address-state"] += 1
            print(f"thearc: skip {slug} — no parseable US address "
                  f"({paras[1] if len(paras) > 1 else ''!r})")
            continue

        rec = {
            "_state": st, "_place_slug": "", "_name": name,
            "categories": ["family-support"],
            "parent_org": "us/the-arc",
            "address": Flow(addr),
        }
        geoid, _ = places.resolve(st, addr.get("city", ""))
        if geoid:
            rec["place"] = geoid
            got["place"] += 1
        if phone:
            rec["phone"] = phone
            got["phone"] += 1
        em = EMAIL_RE.search(m.group(1))
        if em:
            rec["email"] = em.group(0)
            got["email"] += 1
        w = WEBSITE_RE.search(page)
        site = html.unescape(w.group(1)).strip() if w else ""
        if site:
            if not re.match(r"https?://", site, re.I):
                site = "https://" + site
            rec["website"] = site
            got["website"] += 1
        else:
            rec["website"] = url  # the chapter's page on thearc.org
        rec["external_ids"] = Flow(arc_chapter_page=url)
        rec["sources"] = [source_id]
        rec["verified"] = Flow(on=today(), method="scrape")
        records.append(rec)

    if skipped:
        print("skipped:", dict(skipped))
    for field in ("place", "phone", "email", "website"):
        print(f"enriched {got[field]}/{len(records)} chapters with {field}")
    if len(records) < 400:
        raise SystemExit(f"thearc: only {len(records)} chapters — expected ~578")

    records.append({
        "_state": "us", "_place_slug": "", "_name": "The Arc",
        "id": "us/the-arc",
        "aliases": ["The Arc of the United States"],
        "categories": ["family-support"],
        "description": "National organization serving people with "
                       "intellectual and developmental disabilities and "
                       "their families, with state and local chapters "
                       "providing advocacy, programs, and family support.",
        "website": "https://thearc.org",
        "phone": "800-433-5255",
        "service_area": Flow(kind="national"),
        "sources": [source_id],
        "verified": Flow(on=today(), method="scrape"),
    })

    replace_records("orgs", source_id, records)


if __name__ == "__main__":
    main(sys.argv[1:])
