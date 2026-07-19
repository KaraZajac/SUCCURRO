"""NAMI affiliate directory -> org records (mental-health / peer-support).

nami.org exposes its affiliate custom post type via the open WordPress REST API
(~801 records). The API carries name + canonical profile URL whose path encodes
the state (/find-your-local-nami/<state-name>/<slug>/); street-level detail
lives on the profile pages (a later enrichment pass). Facts-only, attributed.

Usage: python3 -m pipeline.nami [--force]
"""
import json
import sys

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


def main(argv):
    force = "--force" in argv
    places = Places()
    source_id = write_source(
        "nami", "affiliate-directory",
        kind="api-feed", publisher="NAMI (National Alliance on Mental Illness)",
        title="NAMI affiliate directory (WordPress REST API)",
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

    records, skipped = [], 0
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
        records.append({
            "_state": state, "_place_slug": "", "_name": name,
            "categories": ["mental-health", "peer-support"],
            "parent_org": "us/nami",
            "website": link,
            "external_ids": Flow(nami=str(a["id"])),
            "sources": [source_id],
            "verified": Flow(on=today(), method="api"),
        })
    if skipped:
        print(f"skipped {skipped} affiliates without a resolvable state")

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
