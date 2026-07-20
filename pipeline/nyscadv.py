"""State DV-coalition member-program directories -> org records
(domestic-violence). Currently: NYSCADV (New York).

Built registry-style so other scrapeable state coalitions can join later
(the 2026-07 sweep estimated 15-25 states with server-rendered
directories): add an entry to COALITIONS with its own parser and source
record. Each coalition owns its records via its own source id.

NYSCADV renders the full member-program directory server-side: <h3>COUNTY
</h3> headings, then <ul><li> entries — program-name anchor (external site),
hotline phone in the visible text (the tel: hrefs are corrupted upstream —
"%20" digits leak into them, so phones are parsed from the display text),
and a short service sentence. Programs listed under several counties are
merged into one record.

DV POLICY — hotline-safe fields only: org name, county context in the
description, hotline phone, website. Street addresses are never recorded
for domestic-violence programs even when published (this page publishes
none). See DATA-RIGHTS.md.

Usage: python3 -m pipeline.nyscadv [--force]
"""
import html
import re
import sys

from .emit import replace_records, today, write_source
from .util import Flow, SOURCES, fetch

PHONE_RE = re.compile(r"\(?\b(\d{3})\)?[-. ]\s*(\d{3})[-. ](\d{4})\b")


def strip_tags(fragment: str) -> str:
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", fragment)).split())


def parse_nyscadv(page: str, source_id: str) -> list[dict]:
    """One record per program; counties merged for multi-county programs."""
    start = page.find('id="county-listing"')
    if start < 0:
        raise SystemExit("nyscadv: county-listing anchor not found — "
                         "page layout changed")
    sec = page[start:]
    by_name: dict[str, dict] = {}
    # some sections carry an <h4> hotline banner and/or <p> note between the
    # county heading and its list (Erie, the NYC area) — tolerate anything
    # short of another heading or list before the <ul>
    heading_re = re.compile(
        r"<h3[^>]*>(.*?)</h3>(?:(?!</?h3|<ul).)*?<ul>(.*?)</ul>", re.S)
    for hm in heading_re.finditer(sec):
        county = strip_tags(hm.group(1)).strip().title()
        if not county:
            continue
        is_county = county.lower() != "new york city area"
        for li in re.findall(r"<li>(.*?)</li>", hm.group(2), re.S):
            text = strip_tags(li)
            # name: the program anchor's text, else the text before the phone
            am = re.search(r'<a href="(https?://[^"]+)"[^>]*>(.*?)</a>', li, re.S)
            if am:
                name = strip_tags(am.group(2))
                website = html.unescape(am.group(1)).strip()
            else:
                name = PHONE_RE.split(text)[0].strip(" -–")
                website = ""
            name = name.strip(" -–")
            if not name:
                print(f"nyscadv: unnamed entry under {county} — skipped")
                continue
            phones = list(PHONE_RE.finditer(text))
            phone = (f"{phones[0].group(1)}-{phones[0].group(2)}-"
                     f"{phones[0].group(3)}") if phones else None
            # the service sentence follows the last phone (or the name when
            # the entry has no parseable phone, e.g. entries carrying only
            # the lettered NYC hotline "(800) 621-HOPE (4673)")
            if phones:
                tail = text[phones[-1].end():]
            elif text.startswith(name):
                tail = text[len(name):]
            else:
                tail = ""
            desc = re.sub(r"^(?:[^A-Za-z]+|HOPE\b|or\b|text\b)*", "", tail,
                          flags=re.I).strip()

            key = name.lower()
            if key in by_name:
                by_name[key]["_counties"].append(county if is_county
                                                 else "New York City area")
                continue
            rec = {
                "_state": "ny", "_place_slug": "", "_name": name,
                "categories": ["domestic-violence"],
                "_counties": [county if is_county else "New York City area"],
                "_is_county": is_county,
            }
            if phone:
                rec["phone"] = phone
            if website:
                rec["website"] = website
            rec["_desc"] = desc
            rec["sources"] = [source_id]
            rec["verified"] = Flow(on=today(), method="scrape")
            by_name[key] = rec

    records = []
    for rec in by_name.values():
        counties = rec.pop("_counties")
        is_county = rec.pop("_is_county")
        desc = rec.pop("_desc")
        if is_county and len(counties) == 1:
            area = f"Serves {counties[0]} County, NY."
            rec["service_area"] = Flow(kind="county", name=counties[0],
                                       state="ny")
        else:
            names = [c if c.endswith("area") else f"{c} County"
                     for c in counties]
            area = f"Serves {', '.join(names)}, NY."
        rec["description"] = f"{area} {desc}".strip() if desc else area
        # field order: description before sources/verified
        ordered = {k: rec[k] for k in
                   ("_state", "_place_slug", "_name", "categories")}
        for k in ("description", "phone", "website", "service_area",
                  "sources", "verified"):
            if k in rec:
                ordered[k] = rec[k]
        records.append(ordered)
    return records


def main(argv):
    force = "--force" in argv
    url = "https://www.nyscadv.org/find-help/program-directory.html"
    page = fetch(url, SOURCES / "nyscadv" / "program-directory.html",
                 force=force).read_text(errors="replace")
    source_id = write_source(
        "nyscadv", "program-directory",
        kind="directory",
        publisher="New York State Coalition Against Domestic Violence",
        title="NYSCADV member program directory",
        url=url, tier="primary",
    )
    records = parse_nyscadv(page, source_id)
    if len(records) < 70:
        raise SystemExit(f"nyscadv: only {len(records)} programs — expected ~100")
    for rec in records:
        assert "address" not in rec  # DV policy: hotline-safe fields only
    replace_records("orgs", source_id, records)


# Registry for future state coalitions: map of state -> (parser, source
# fields). NNEDV (pipeline/nnedv.py) already provides the coalitions
# themselves; this module is for member-program directories.
COALITIONS = {"ny": parse_nyscadv}


if __name__ == "__main__":
    main(sys.argv[1:])
