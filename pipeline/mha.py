"""Mental Health America affiliate pages -> org records (mental-health).

mhanational.org publishes a per-affiliate WordPress page; the affiliates
sitemap (affiliates-sitemap.xml) enumerates all of them (first <loc> is the
/affiliates/ index page and is skipped). Each page's `the-content` block holds
an "Affiliate Address" paragraph (street / City, ST ZIP / United States) plus
labeled Phone/Website lines; any of those may be absent. Pages are fetched
throttled (util.get sleeps per host) and cached under sources/mha/affiliates/.

Usage: python3 -m pipeline.mha [--force]
"""
import html
import re
import sys

from .emit import Places, replace_records, today, write_source
from .util import Flow, SOURCES, fetch

SITEMAP = "https://mhanational.org/affiliates-sitemap.xml"

LOC_RE = re.compile(r"<loc>([^<]+)</loc>")
H1_RE = re.compile(r"<h1[^>]*>(.*?)</h1>", re.S)
CONTENT_RE = re.compile(r'<div class="the-content ?">(.*?)</div>', re.S)
CITY_RE = re.compile(r"^(?P<city>.+?),\s*(?P<state>[A-Z]{2})\.?,?\s+(?P<zip>\d{5})(-\d{4})?$")
WEBSITE_RE = re.compile(r"Website:?\s*</strong>\s*<a href=\"([^\"]+)\"", re.I)
PHONE_RE = re.compile(r"Phone:?\s*</strong>\s*([^<]+)", re.I)


def norm_phone(raw: str) -> str | None:
    digits = re.sub(r"\D", "", raw or "")
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    if len(digits) == 10:
        return f"{digits[:3]}-{digits[3:6]}-{digits[6:]}"
    return None


def parse_address(block_text: str) -> dict:
    """Lines after 'Affiliate Address' up to a blank/label line -> address."""
    lines = [ln.strip() for ln in block_text.splitlines() if ln.strip()]
    try:
        start = next(i for i, ln in enumerate(lines)
                     if ln.lower() in ("affiliate address", "address:"))
    except StopIteration:
        return {}
    street: list[str] = []
    for ln in lines[start + 1:]:
        if ln == "United States" or ":" in ln:
            break
        m = CITY_RE.match(ln)
        if m:
            addr = {"city": m["city"], "state": m["state"].lower(), "zip": m["zip"]}
            if street:
                addr = {"street": ", ".join(street), **addr}
            return addr
        street.append(ln)
    return {}


def main(argv):
    force = "--force" in argv
    places = Places()
    sitemap = fetch(SITEMAP, SOURCES / "mha" / "affiliates-sitemap.xml", force=force).read_text()
    urls = [u for u in LOC_RE.findall(sitemap) if u.rstrip("/").split("/")[-1] != "affiliates"]
    if len(urls) < 100:
        raise SystemExit(f"mha: sitemap lists only {len(urls)} affiliate pages — expected ~132")

    source_id = write_source(
        "mha", "affiliate-pages",
        kind="directory", publisher="Mental Health America",
        title="MHA affiliate pages (affiliates sitemap)",
        url="https://mhanational.org/affiliates/", tier="primary",
    )

    records, skipped = [], []
    for url in urls:
        slug = url.rstrip("/").split("/")[-1]
        page = fetch(url, SOURCES / "mha" / "affiliates" / f"{slug}.html",
                     force=force).read_text()
        h1 = H1_RE.search(page)
        name = html.unescape(re.sub(r"<[^>]+>", "", h1.group(1))).strip() if h1 else ""
        content = CONTENT_RE.search(page)
        body = content.group(1) if content else ""
        text = html.unescape(re.sub(r"<br ?/?>", "\n", re.sub(r"</p>", "\n\n", body)))
        text = re.sub(r"<[^>]+>", "", text).replace("\xa0", " ")
        addr = parse_address(text)
        state = addr.get("state")
        if not name or not state or state not in places.by_state:
            skipped.append(slug)
            continue
        geoid, _ = places.resolve(state, addr.get("city", ""))
        rec = {
            "_state": state, "_place_slug": "", "_name": name,
            "categories": ["mental-health"],
            "parent_org": "us/mental-health-america",
            "address": Flow(addr),
        }
        if geoid:
            rec["place"] = geoid
        m = PHONE_RE.search(body)
        phone = norm_phone(m.group(1)) if m else None
        if phone:
            rec["phone"] = phone
        m = WEBSITE_RE.search(body)
        if m:
            website = html.unescape(m.group(1)).strip()
            rec["website"] = website if website.startswith("http") else f"https://{website}"
        rec["sources"] = [source_id]
        rec["verified"] = Flow(on=today(), method="scrape")
        records.append(rec)
    if skipped:
        print(f"skipped {len(skipped)} pages without name/parseable state: {', '.join(skipped)}")

    records.append({
        "_state": "us", "_place_slug": "", "_name": "Mental Health America",
        "id": "us/mental-health-america",
        "categories": ["mental-health"],
        "website": "https://mhanational.org",
        "service_area": Flow(kind="national"),
        "sources": [source_id],
        "verified": Flow(on=today(), method="scrape"),
    })

    if len(records) < 100:
        raise SystemExit(f"mha: only {len(records)} records — expected ~130; aborting")
    replace_records("orgs", source_id, records)


if __name__ == "__main__":
    main(sys.argv[1:])
