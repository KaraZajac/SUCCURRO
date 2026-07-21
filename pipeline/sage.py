"""SAGE (Advocacy & Services for LGBTQ+ Elders) partner network -> org records.

SAGE's old SAGENet affiliate program is now the SAGECollab network (~118
partner nonprofits serving LGBTQ+ elders). sageusa.org exposes the partner
list via the open WordPress REST API (`sage_collab_center` custom post type;
`link` is the partner's own website, `state` is a taxonomy term id resolved
via /wp/v2/state). No addresses or phones are published. Partners that
already exist as org records from another source (CenterLink centers overlap)
are skipped, not duplicated.

Verified 2026-07-20: the SAGE National LGBTQ+ Elder Hotline (877-360-5428)
was discontinued in 2023 (sageusa.org/find-support/hotline-notice/) — do not
re-add it. Facts-only re-expression, attributed (see DATA-RIGHTS.md).

Usage: python3 -m pipeline.sage [--force]
"""
import html
import json
import sys

from .emit import Places, norm, replace_records, today, write_source
from .util import DATA, Flow, SOURCES, fetch, load_yaml

API = ("https://www.sageusa.org/wp-json/wp/v2/sage_collab_center"
       "?per_page=100&page={page}&_fields=id,slug,link,title,state")
STATE_API = ("https://www.sageusa.org/wp-json/wp/v2/state"
             "?per_page=100&_fields=id,name,slug")

STATE_SLUGS = {
    "alabama": "al", "alaska": "ak", "arizona": "az", "arkansas": "ar",
    "california": "ca", "colorado": "co", "connecticut": "ct", "delaware": "de",
    "d-c": "dc", "district-of-columbia": "dc", "florida": "fl", "georgia": "ga",
    "hawaii": "hi", "idaho": "id", "illinois": "il", "indiana": "in",
    "iowa": "ia", "kansas": "ks", "kentucky": "ky", "louisiana": "la",
    "maine": "me", "maryland": "md", "massachusetts": "ma", "michigan": "mi",
    "minnesota": "mn", "mississippi": "ms", "missouri": "mo", "montana": "mt",
    "nebraska": "ne", "nevada": "nv", "new-hampshire": "nh", "new-jersey": "nj",
    "new-mexico": "nm", "new-york": "ny", "north-carolina": "nc",
    "north-dakota": "nd", "ohio": "oh", "oklahoma": "ok", "oregon": "or",
    "pennsylvania": "pa", "puerto-rico": "pr", "rhode-island": "ri",
    "south-carolina": "sc", "south-dakota": "sd", "tennessee": "tn",
    "texas": "tx", "utah": "ut", "vermont": "vt", "virginia": "va",
    "washington": "wa", "west-virginia": "wv", "wisconsin": "wi",
    "wyoming": "wy",
}


def main(argv):
    force = "--force" in argv
    places = Places()

    terms = json.loads(fetch(STATE_API, SOURCES / "sage" / "states.json",
                             force=force).read_text())
    term_state = {}
    for t in terms:
        st = STATE_SLUGS.get(t.get("slug", ""))
        if st:
            term_state[t["id"]] = st

    partners, page = [], 1
    while page <= 5:
        cache = SOURCES / "sage" / f"collab-p{page}.json"
        batch = json.loads(fetch(API.format(page=page), cache, force=force).read_text())
        partners.extend(batch)
        if len(batch) < 100:
            break
        page += 1
    if len(partners) < 60:
        raise SystemExit(f"sage: only {len(partners)} SAGECollab partners — "
                         "expected ~118; aborting")

    source_id = write_source(
        "sage", "collab-partners",
        kind="api-feed", publisher="SAGE (Advocacy & Services for LGBTQ+ Elders)",
        title="SAGECollab partner network (WordPress REST API)",
        url="https://www.sageusa.org/advocacy-partnerships/partnerships/sagecollab/",
        tier="primary",
    )

    # orgs already on disk from other sources — the SAGECollab list overlaps
    # CenterLink's member centers; those are skipped, not duplicated
    existing = set()
    for path in sorted((DATA / "orgs").rglob("*.yaml")):
        rec = load_yaml(path)
        if source_id not in (rec.get("sources") or []):
            existing.add(norm(rec["name"]))

    records, skipped_dup, skipped_bad = [], 0, 0
    for p in partners:
        name = html.unescape((p.get("title", {}).get("rendered") or "")).strip()
        website = (p.get("link") or "").strip()
        if not name:
            skipped_bad += 1
            continue
        if norm(name) in existing:
            skipped_dup += 1
            continue
        states = [term_state[t] for t in p.get("state") or [] if t in term_state]
        st = states[0] if states else "us"
        if st != "us" and st not in places.by_state:
            st = "us"
        rec = {
            "_state": st, "_place_slug": "", "_name": name,
            "categories": ["lgbtq", "seniors"],
            "parent_org": "us/sage",
        }
        if website:
            rec["website"] = website
        rec["external_ids"] = Flow(sage=str(p["id"]))
        rec["sources"] = [source_id]
        rec["verified"] = Flow(on=today(), method="api")
        records.append(rec)

    records.append({
        "_state": "us", "_place_slug": "", "_name": "SAGE",
        "id": "us/sage",
        "aliases": ["SAGE — Advocacy & Services for LGBTQ+ Elders",
                    "Services & Advocacy for GLBT Elders"],
        "categories": ["lgbtq", "seniors"],
        "description": "National advocacy and services organization for "
                       "LGBTQ+ elders; its SAGECollab network of local "
                       "partner nonprofits offers programs and services "
                       "across the country. Note: the former SAGE National "
                       "LGBTQ+ Elder Hotline was discontinued in 2023.",
        "website": "https://www.sageusa.org",
        "service_area": Flow(kind="national"),
        "sources": [source_id],
        "verified": Flow(on=today(), method="scrape"),
    })

    n = len(records) - 1
    print(f"sage: {n} SAGECollab partner orgs + umbrella "
          f"({skipped_dup} skipped as duplicates of existing orgs, "
          f"{skipped_bad} unusable)")
    if n < 20:
        raise SystemExit(f"sage: only {n} partners — floor 20; aborting")
    replace_records("orgs", source_id, records)


if __name__ == "__main__":
    main(sys.argv[1:])
