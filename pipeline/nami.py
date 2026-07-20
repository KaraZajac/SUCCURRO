"""NAMI affiliate directory -> org records (mental-health / peer-support).

nami.org exposes its affiliate custom post type via the open WordPress REST API
(~801 records). The API carries name + canonical profile URL whose path encodes
the state (/find-your-local-nami/<state-name>/<slug>/). Each profile page holds
a "Contact Information" <dl> (affiliate-contact-information__content) with
labeled Address / Website / Email / Phone / Service Area items, any of which may
be absent (state-office pages have the same block; ".../<state>/events/" listing
pages have none). Emails are Cloudflare-obfuscated (data-cfemail hex, XOR-key
first byte); no page embeds coordinates. Pages are fetched throttled (util.get
sleeps per host) and cached under sources/nami/pages/. Facts-only, attributed.

Usage: python3 -m pipeline.nami [--force]
"""
import html
import json
import re
import sys
from collections import Counter

from .emit import Places, replace_records, today, write_source
from .util import Flow, SOURCES, fetch

API = ("https://www.nami.org/wp-json/wp/v2/affiliate"
       "?per_page=100&page={page}&_fields=id,slug,link,title")

STATE_CODES = {
    "alabama": "al", "alaska": "ak", "arizona": "az", "arkansas": "ar",
    "california": "ca", "colorado": "co", "connecticut": "ct", "delaware": "de",
    "district-of-columbia": "dc", "florida": "fl", "georgia": "ga", "hawaii": "hi",
    "idaho": "id", "illinois": "il", "indiana": "in", "iowa": "ia", "kansas": "ks",
    "kentucky": "ky", "louisiana": "la", "maine": "me", "maryland": "md",
    "massachusetts": "ma", "michigan": "mi", "minnesota": "mn", "mississippi": "ms",
    "missouri": "mo", "montana": "mt", "nebraska": "ne", "nevada": "nv",
    "new-hampshire": "nh", "new-jersey": "nj", "new-mexico": "nm", "new-york": "ny",
    "north-carolina": "nc", "north-dakota": "nd", "ohio": "oh", "oklahoma": "ok",
    "oregon": "or", "pennsylvania": "pa", "puerto-rico": "pr", "rhode-island": "ri",
    "south-carolina": "sc", "south-dakota": "sd", "tennessee": "tn", "texas": "tx",
    "utah": "ut", "vermont": "vt", "virginia": "va", "washington": "wa",
    "west-virginia": "wv", "wisconsin": "wi", "wyoming": "wy",
}

CONTACT_RE = re.compile(
    r'<dl class="affiliate-contact-information__content">(.*?)</dl>', re.S)
ITEM_RE = re.compile(
    r'<dt[^>]*affiliate-contact-information__item-label[^>]*>\s*([^<]+?)\s*</dt>\s*'
    r'<dd[^>]*>(.*?)</dd>', re.S)
CITY_RE = re.compile(r"^(?P<city>.+?),\s*(?P<state>[A-Z]{2})\.?,?"
                     r"(?:\s+(?P<zip>\d{5}(?:-\d{4})?))?$")
HREF_RE = re.compile(r'href="([^"]+)"')
CFEMAIL_RE = re.compile(r'data-cfemail="([0-9a-fA-F]+)"')
CFHREF_RE = re.compile(r'/cdn-cgi/l/email-protection#([0-9a-fA-F]+)')
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
PHONE_RE = re.compile(r"\(?(\d{3})\)?[\s./-]?(\d{3})[\s.-]?(\d{4})")


def strip_tags(fragment: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", "", fragment)).replace("\xa0", " ").strip()


def contact_items(page: str) -> dict:
    """Label -> raw dd-HTML from the profile page's Contact Information block."""
    m = CONTACT_RE.search(page)
    if not m:
        return {}
    return {label.strip().lower(): dd for label, dd in ITEM_RE.findall(m.group(1))}


def parse_website(dd: str) -> str | None:
    m = HREF_RE.search(dd)
    if not m:
        return None
    url = html.unescape(m.group(1)).strip()
    if not url or url.startswith(("mailto:", "tel:", "/", "#")):
        return None
    if not re.match(r"https?://", url, re.I):
        url = "https://" + url
    if re.match(r"https?://(www\.)?nami\.org(/|$)", url, re.I):
        return None  # the profile page itself is not the affiliate's own site
    return url


def decode_cfemail(hexstr: str) -> str | None:
    try:
        data = bytes.fromhex(hexstr)
    except ValueError:
        return None
    if len(data) < 2:
        return None
    email = "".join(chr(b ^ data[0]) for b in data[1:])
    return email if EMAIL_RE.fullmatch(email) else None


def parse_email(dd: str) -> str | None:
    m = CFEMAIL_RE.search(dd) or CFHREF_RE.search(dd)
    if m:
        return decode_cfemail(m.group(1))
    m = re.search(r'href="mailto:([^"?]+)', dd)
    text = html.unescape(m.group(1)) if m else strip_tags(dd)
    m = EMAIL_RE.search(text)
    return m.group(0) if m else None


_KEYPAD = str.maketrans("ABCDEFGHIJKLMNOPQRSTUVWXYZ",
                        "22233344455566677778889999")


def parse_phone(dd: str) -> str | None:
    text = strip_tags(dd)
    m = PHONE_RE.search(text) or PHONE_RE.search(text.upper().translate(_KEYPAD))
    return "-".join(m.groups()) if m else None


def parse_address(dd: str) -> dict:
    """<br>-separated lines, one of which is 'City, ST [ZIP]'. No city -> {}."""
    lines = [strip_tags(ln) for ln in re.split(r"<br\s*/?>", dd)]
    lines = [ln for ln in lines if ln and ln.lower() != "united states"]
    for i, ln in enumerate(lines):
        m = CITY_RE.match(ln)
        if not m:
            continue
        addr = {}
        if i >= 1:
            addr["street"] = lines[0]
        if i >= 2:
            addr["street2"] = ", ".join(lines[1:i])
        addr.update(city=m["city"], state=m["state"].lower())
        if m["zip"]:
            addr["zip"] = m["zip"]
        return addr
    return {}


def main(argv):
    force = "--force" in argv
    places = Places()
    source_id = write_source(
        "nami", "affiliate-directory",
        kind="api-feed", publisher="NAMI (National Alliance on Mental Illness)",
        title="NAMI affiliate directory (WordPress REST API + profile pages)",
        url="https://www.nami.org/find-your-local-nami/", tier="primary",
    )

    affiliates, page = [], 1
    while page <= 20:
        cache = SOURCES / "nami" / f"affiliates-p{page}.json"
        batch = json.loads(fetch(API.format(page=page), cache, force=force).read_text())
        affiliates.extend(batch)
        if len(batch) < 100:
            break
        page += 1
    if len(affiliates) < 600:
        raise SystemExit(f"nami: only {len(affiliates)} affiliates — expected ~800")

    records, skipped, got = [], 0, Counter()
    for a in affiliates:
        name = (a.get("title", {}).get("rendered") or "").strip()
        link = a.get("link") or ""
        parts = [p for p in link.split("/") if p]
        # .../find-your-local-nami/<state-name>/<slug>
        state = None
        if "find-your-local-nami" in parts:
            idx = parts.index("find-your-local-nami")
            if idx + 1 < len(parts):
                state = STATE_CODES.get(parts[idx + 1])
        if not name or not state or state not in places.by_state:
            skipped += 1
            continue

        # profile-page enrichment (path segments after the prefix are a unique key)
        page_slug = "-".join(parts[idx + 1:])
        page_html = fetch(link, SOURCES / "nami" / "pages" / f"{page_slug}.html",
                          force=force).read_text(errors="replace")
        items = contact_items(page_html)

        rec = {
            "_state": state, "_place_slug": "", "_name": name,
            "categories": ["mental-health", "peer-support"],
            "parent_org": "us/nami",
        }
        addr = parse_address(items.get("address", ""))
        if addr:
            rec["address"] = Flow(addr)
            got["address"] += 1
            geoid, _ = places.resolve(addr["state"], addr["city"])
            if geoid:
                rec["place"] = geoid
                got["place"] += 1
        website = parse_website(items.get("website", ""))
        external_ids = Flow(nami=str(a["id"]))
        if website:
            rec["website"] = website
            external_ids["nami_profile"] = link  # own site wins; keep the profile
            got["website"] += 1
        else:
            rec["website"] = link
        phone = parse_phone(items.get("phone", ""))
        if phone:
            rec["phone"] = phone
            got["phone"] += 1
        email = parse_email(items.get("email", ""))
        if email:
            rec["email"] = email
            got["email"] += 1
        enriched = bool(addr or website or phone or email)
        rec["external_ids"] = external_ids
        rec["sources"] = [source_id]
        rec["verified"] = Flow(on=today(), method="scrape" if enriched else "api")
        records.append(rec)
    if skipped:
        print(f"skipped {skipped} affiliates without a resolvable state")
    for field in ("website", "phone", "email", "address", "place"):
        print(f"enriched {got[field]}/{len(records)} affiliates with {field}")

    records.append({
        "_state": "us", "_place_slug": "", "_name": "NAMI",
        "id": "us/nami",
        "categories": ["mental-health", "peer-support"],
        "description": "National Alliance on Mental Illness — HelpLine 800-950-6264, text NAMI to 62640.",
        "website": "https://www.nami.org",
        "phone": "800-950-6264",
        "service_area": Flow(kind="national"),
        "sources": [source_id],
        "verified": Flow(on=today(), method="api"),
    })

    replace_records("orgs", source_id, records)


if __name__ == "__main__":
    main(sys.argv[1:])
