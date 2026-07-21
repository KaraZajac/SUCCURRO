"""ILRU Centers for Independent Living directory -> org records.

ILRU (Independent Living Research Utilization) maintains the national CIL
directory under its ACL/NIDILRR-funded CIL-NET project: a hub page linking one
page per state/territory (ilru.org/cil-directory/<st>), each a uniform list of
offices — <h2 class="h4"> name, then Address/Website/Email dt-dd pairs, a
Phone Numbers dl (Local/Fax/Toll-Free/Accessible), a Director block, and a
Counties Served paragraph. Every listed office becomes an org record (main and
branch offices are separately listed upstream, with their own addresses and
phones). Director names/emails are people, not org facts — never copied
(smallchapters/bpusa convention).

ToS check 2026-07-21: no robots.txt (404), no terms-of-use page; the privacy
policy is privacy-only and the footer carries only a standard copyright line.
Facts-only re-expression, attributed (DATA-RIGHTS.md).

Usage: python3 -m pipeline.cils [--force]
"""
import html
import re
import sys
from collections import Counter

from .emit import Places, replace_records, today, write_source
from .util import Flow, SOURCES, fetch

HUB = "https://www.ilru.org/projects/cil-net/cil-center-and-association-directory"

STATE_RE = re.compile(r'href="(?:https://www\.ilru\.org)?/cil-directory/([a-z]{2})"')
ENTRY_SPLIT = re.compile(r'<h2 class="h4">')
NAME_RE = re.compile(r"^(.*?)</h2>", re.S)
ADDR_RE = re.compile(r"Address:</dt>\s*<dd[^>]*>\s*(.*?)\s*</dd>", re.S)
WEBSITE_RE = re.compile(r'Website:</dt>\s*<dd[^>]*>\s*<a href="([^"]+)"')
EMAIL_RE = re.compile(r'Email:</dt>\s*<dd[^>]*>\s*<a href="mailto:([^"?]+)')
PHONES_RE = re.compile(r"Phone Numbers:</h3>\s*<dl[^>]*>(.*?)</dl>", re.S)
PHONE_PAIR_RE = re.compile(
    r"<dt[^>]*>\s*([^<:]+):\s*</dt>\s*<dd[^>]*>\s*<a[^>]*href=\"tel:([^\"]+)\"")
COUNTIES_RE = re.compile(r"Counties Served:</h3>\s*<p[^>]*>(.*?)</p>", re.S)
CSZ_RE = re.compile(
    r"^(?P<city>.+?),\s*(?P<st>[A-Za-z]{2})\.?\s*(?P<zip>\d{5}(-\d{4})?)?$")

US_STATE_CODES = {
    "al", "ak", "as", "az", "ar", "ca", "co", "ct", "de", "dc", "fl", "ga",
    "gu", "hi", "id", "il", "in", "ia", "ks", "ky", "la", "me", "md", "ma",
    "mi", "mn", "ms", "mo", "mt", "ne", "nv", "nh", "nj", "nm", "ny", "nc",
    "nd", "mp", "oh", "ok", "or", "pa", "pr", "ri", "sc", "sd", "tn", "tx",
    "ut", "vt", "vi", "va", "wa", "wv", "wi", "wy",
}

# preferred voice-line labels, best first (TTY/VP/Fax lines are not `phone`)
PHONE_PRIORITY = ("local", "tollfree", "main", "office", "voice", "phone")

DESCRIPTION = "Center for Independent Living — disability services and advocacy."


def strip_tags(fragment: str) -> str:
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", fragment)).split())


def clean_phone(raw: str) -> str | None:
    digits = re.sub(r"\D", "", raw or "")
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    if len(digits) == 10:
        return f"{digits[:3]}-{digits[3:6]}-{digits[6:]}"
    return None


def parse_address(dd: str) -> dict:
    """Split the Address dd on <br/>; the last line is 'City, ST ZIP'."""
    lines = [strip_tags(p) for p in re.split(r"<br\s*/?>", dd)]
    lines = [ln for ln in lines if ln]
    if not lines:
        return {}
    m = CSZ_RE.match(lines[-1])
    if not m or m["st"].lower() not in US_STATE_CODES:
        return {}
    addr = {"city": m["city"].strip(), "state": m["st"].lower()}
    if m["zip"]:
        addr["zip"] = m["zip"]
    if len(lines) > 1:
        addr = {"street": ", ".join(lines[:-1]), **addr}
    return addr


def pick_phone(chunk: str) -> str | None:
    m = PHONES_RE.search(chunk)
    if not m:
        return None
    labeled = {}
    for label, number in PHONE_PAIR_RE.findall(m.group(1)):
        key = re.sub(r"[^a-z]", "", label.lower())
        labeled.setdefault(key, clean_phone(number))
    for key in PHONE_PRIORITY:
        if labeled.get(key):
            return labeled[key]
    return None


def service_area(chunk: str, st: str) -> Flow | None:
    m = COUNTIES_RE.search(chunk)
    if not m:
        return None
    text = strip_tags(m.group(1)).rstrip(".")
    if not text:
        return None
    if "statewide" in text.lower() or text.lower() == "all":
        return Flow(kind="state", state=st)
    counties = [c.strip() for c in re.split(r",| and ", text) if c.strip()]
    if len(counties) == 1:
        return Flow(kind="county", name=counties[0], state=st)
    if len(text) <= 120:
        return Flow(kind="regional", name=f"{text} counties", state=st)
    return Flow(kind="regional", state=st)


def main(argv):
    force = "--force" in argv
    places = Places()
    hub = fetch(HUB, SOURCES / "ilru" / "directory-hub.html",
                force=force).read_text(errors="replace")
    states = sorted(set(STATE_RE.findall(hub)) & US_STATE_CODES)
    if len(states) < 50:
        raise SystemExit(f"cils: only {len(states)} state links on the hub "
                         "page — layout changed")

    source_id = write_source(
        "ilru", "cil-directory",
        kind="directory", publisher="ILRU (Independent Living Research Utilization)",
        title="ILRU CIL Center and Association Directory (per-state pages)",
        url=HUB, tier="secondary",
        notes="ILRU maintains the national CIL directory under the "
              "ACL/NIDILRR-funded CIL-NET project; entries are the "
              "federally funded, consumer-controlled Centers for "
              "Independent Living and their branch offices.",
    )

    records, got = [], Counter()
    for st in states:
        page = fetch(f"https://www.ilru.org/cil-directory/{st}",
                     SOURCES / "ilru" / f"cil-{st}.html",
                     force=force).read_text(errors="replace")
        chunks = ENTRY_SPLIT.split(page)[1:]
        for chunk in chunks:
            m = NAME_RE.match(chunk)
            if not m:
                continue
            name = strip_tags(m.group(1))
            if not name:
                continue
            addr = {}
            am = ADDR_RE.search(chunk)
            if am:
                addr = parse_address(am.group(1))
            rec_state = addr.get("state", st)
            rec = {
                "_state": rec_state, "_place_slug": "", "_name": name,
                "categories": ["family-support"],
                "description": DESCRIPTION,
            }
            if addr:
                rec["address"] = Flow(addr)
                geoid, _ = places.resolve(rec_state, addr["city"])
                if geoid:
                    rec["place"] = geoid
                    got["place"] += 1
            w = WEBSITE_RE.search(chunk)
            if w:
                url = html.unescape(w.group(1)).strip()
                if not re.match(r"https?://", url, re.I):
                    url = "https://" + url
                rec["website"] = url
                got["website"] += 1
            em = EMAIL_RE.search(chunk)
            if em:
                rec["email"] = html.unescape(em.group(1)).strip()
                got["email"] += 1
            phone = pick_phone(chunk)
            if phone:
                rec["phone"] = phone
                got["phone"] += 1
            area = service_area(chunk, rec_state)
            if area:
                rec["service_area"] = area
                got["service_area"] += 1
            rec["sources"] = [source_id]
            rec["verified"] = Flow(on=today(), method="scrape")
            records.append(rec)
        print(f"cils {st}: {len(chunks)} offices")

    for field in ("place", "phone", "email", "website", "service_area"):
        print(f"enriched {got[field]}/{len(records)} offices with {field}")
    if len(records) < 300:
        raise SystemExit(f"cils: only {len(records)} offices — floor is 300")
    replace_records("orgs", source_id, records)


if __name__ == "__main__":
    main(sys.argv[1:])
