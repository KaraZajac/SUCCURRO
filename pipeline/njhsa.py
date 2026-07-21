"""Network of Jewish Human Service Agencies members -> org records (family-support).

The member locator at networkjhsa.org/member-locator/ (note: njhsa.org is an
unrelated horse-show association) loads its data from a public admin-ajax
endpoint, action=fetch_users, which with empty filters returns the full member
list as JSON: company, city, state, zipcode, website, country, upstream id.
~181 members; only US ones are emitted (the network also spans Canada and
Israel). Facts-only re-expression, attributed (see DATA-RIGHTS.md: robots.txt
permissive; the site's terms-conditions page expressly permits copying and
distributing site content for not-for-profit purposes).

Usage: python3 -m pipeline.njhsa [--force]
"""
import json
import re
import sys

from .emit import Places, replace_records, today, write_source
from .util import Flow, SOURCES, fetch

API = ("https://networkjhsa.org/wp-admin/admin-ajax.php"
       "?action=fetch_users&country=&state=&search=")

STATES = {
    "al", "ak", "az", "ar", "ca", "co", "ct", "de", "dc", "fl", "ga", "hi",
    "id", "il", "in", "ia", "ks", "ky", "la", "me", "md", "ma", "mi", "mn",
    "ms", "mo", "mt", "ne", "nv", "nh", "nj", "nm", "ny", "nc", "nd", "oh",
    "ok", "or", "pa", "pr", "ri", "sc", "sd", "tn", "tx", "ut", "vt", "vi",
    "va", "wa", "wv", "wi", "wy",
}


def ensure_https(url: str) -> str:
    url = url.strip()
    return url if re.match(r"https?://", url, re.I) else f"https://{url}"


def main(argv):
    force = "--force" in argv
    places = Places()

    raw = json.loads(fetch(API, SOURCES / "njhsa" / "members.json",
                           force=force).read_text())
    users = (raw.get("data") or {}).get("users") if isinstance(raw, dict) else None
    if not users:
        raise SystemExit("njhsa: fetch_users returned no member list — endpoint changed")

    source_id = write_source(
        "njhsa", "member-locator",
        kind="api-feed", publisher="Network of Jewish Human Service Agencies",
        title="NJHSA member locator (fetch_users endpoint)",
        url="https://networkjhsa.org/member-locator/", tier="primary",
    )

    records, skipped_non_us = [], 0
    for u in users:
        name = " ".join((u.get("company") or "").split())
        country = (u.get("country") or "").strip().lower()
        if not name:
            continue  # a few fully blank rows come back from the endpoint
        if not country.startswith("united states"):
            skipped_non_us += 1  # Canada / Israel members
            continue
        state = (u.get("state") or "").strip().lower()
        if state not in STATES:
            print(f"njhsa: {name!r} has non-US state {state!r} — skipped")
            continue
        rec = {
            "_state": state, "_place_slug": "", "_name": name,
            "categories": ["family-support"],
            "parent_org": "us/njhsa",
        }
        city = (u.get("city") or "").strip()
        if city:
            addr = {"city": city, "state": state}
            zip_code = (u.get("zipcode") or "").strip()
            if re.fullmatch(r"\d{5}(-\d{4})?", zip_code):
                addr["zip"] = zip_code
            rec["address"] = Flow(addr)
            geoid, _ = places.resolve(state, city)
            if geoid:
                rec["place"] = geoid
        website = (u.get("website") or "").strip()
        if website:
            rec["website"] = ensure_https(website)
        if u.get("id"):
            rec["external_ids"] = Flow(njhsa=str(u["id"]))
        rec["sources"] = [source_id]
        rec["verified"] = Flow(on=today(), method="api")
        records.append(rec)
    print(f"njhsa: {len(records)} US members ({skipped_non_us} non-US skipped)")

    n_members = len(records)
    records.append({
        "_state": "us", "_place_slug": "",
        "_name": "Network of Jewish Human Service Agencies",
        "id": "us/njhsa",
        "aliases": ["NJHSA"],
        "categories": ["family-support"],
        "description": "Membership association of Jewish human service "
                       "agencies in the United States, Canada, and Israel — "
                       "member agencies provide family, older-adult, career, "
                       "mental health, and resettlement services.",
        "website": "https://networkjhsa.org",
        "service_area": Flow(kind="national"),
        "sources": [source_id],
        "verified": Flow(on=today(), method="api"),
    })

    if n_members < 90:
        raise SystemExit(f"njhsa: only {n_members} US members — expected ~150; aborting")
    replace_records("orgs", source_id, records)


if __name__ == "__main__":
    main(sys.argv[1:])
