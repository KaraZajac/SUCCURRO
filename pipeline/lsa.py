"""Lutheran Services in America member network -> org records (family-support).

The our-network page embeds a Google My Maps "LSA Member Network Map" whose KML
export (maps.google.com/maps/d/kml?forcekml=1) carries one placemark per member
location: org name, street/city/state, website, and per-service flags (senior /
family-children / disability / refugee / housing / healthcare). No coordinates —
placemarks are address-only, so geo comes from our own place registry. ~283
member orgs across ~1,080 locations; the map id is read from the page's iframe,
not hardcoded. Multi-location orgs are deduped by name and filed under the state
where they list the most locations; an address is kept only when the org has
exactly one location. Facts-only re-expression, attributed (see DATA-RIGHTS.md:
robots.txt permissive, no terms-of-use page, privacy policy carries no content
restrictions).

Usage: python3 -m pipeline.lsa [--force]
"""
import re
import sys
import xml.etree.ElementTree as ET
from collections import Counter

from .emit import Places, replace_records, today, write_source
from .util import Flow, SOURCES, fetch

PAGE_URL = "https://lutheranservices.org/our-network/"
KML_URL = "https://www.google.com/maps/d/kml?mid={mid}&forcekml=1"
MID_RE = re.compile(r"google\.com/maps/d/(?:u/\d+/)?embed\?mid=([A-Za-z0-9_-]+)")
KML_NS = {"k": "http://www.opengis.net/kml/2.2"}

STATES = {
    "al", "ak", "as", "az", "ar", "ca", "co", "ct", "de", "dc", "fl", "ga", "gu",
    "hi", "id", "il", "in", "ia", "ks", "ky", "la", "me", "md", "ma", "mi", "mn",
    "ms", "mo", "mt", "ne", "nv", "nh", "nj", "nm", "ny", "nc", "nd", "mp", "oh",
    "ok", "or", "pa", "pr", "ri", "sc", "sd", "tn", "tx", "ut", "vt", "vi", "va",
    "wa", "wv", "wi", "wy",
}

# a handful of rows carry full state names instead of postal codes
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
    "pennsylvania": "pa", "puerto rico": "pr", "rhode island": "ri",
    "south carolina": "sc", "south dakota": "sd", "tennessee": "tn",
    "texas": "tx", "utah": "ut", "vermont": "vt", "virginia": "va",
    "washington": "wa", "west virginia": "wv", "wisconsin": "wi",
    "wyoming": "wy",
}

# the map's per-org service flags -> taxonomy tokens beyond the family-support
# base (Disability and Refugee services have no taxonomy token yet)
SERVICE_TOKENS = {
    "Senior Services": "seniors",
    "Housing Services": "housing",
    "Healthcare Services": "health",
}


def norm_state(raw: str) -> str | None:
    raw = (raw or "").strip().lower()
    if raw in STATES:
        return raw
    return STATE_NAMES.get(raw)


def ensure_https(url: str) -> str:
    url = url.strip()
    return url if re.match(r"https?://", url, re.I) else f"https://{url}"


def main(argv):
    force = "--force" in argv
    places = Places()

    page = fetch(PAGE_URL, SOURCES / "lsa" / "our-network.html",
                 force=force).read_text(errors="replace")
    m = MID_RE.search(page)
    if not m:
        raise SystemExit("lsa: member-network map iframe not found — page layout changed")
    kml_path = fetch(KML_URL.format(mid=m.group(1)),
                     SOURCES / "lsa" / "member-network.kml", force=force)

    doc = ET.parse(kml_path).getroot().find("k:Document", KML_NS)
    if doc is None:
        raise SystemExit("lsa: KML has no Document element")
    # the all-members layer; the other folders repeat members per service
    folders = doc.findall("k:Folder", KML_NS)
    main_folder = max(folders, key=lambda f: len(f.findall("k:Placemark", KML_NS)),
                      default=None)
    if main_folder is None:
        raise SystemExit("lsa: KML has no folders")

    orgs: dict[str, dict] = {}
    skipped = 0
    for pm in main_folder.findall("k:Placemark", KML_NS):
        name = " ".join((pm.findtext("k:name", "", KML_NS) or "").split())
        ext = {d.get("name"): (d.findtext("k:value", "", KML_NS) or "").strip()
               for d in pm.findall("k:ExtendedData/k:Data", KML_NS)}
        state = norm_state(ext.get("State", ""))
        if not name or not state:
            skipped += 1
            continue
        org = orgs.setdefault(name, {
            "states": Counter(), "rows": [], "website": "", "tokens": set()})
        org["states"][state] += 1
        org["rows"].append({"street": ext.get("Address", ""),
                            "city": ext.get("Locations", ""), "state": state})
        if ext.get("Organization Website"):
            org["website"] = ext["Organization Website"]
        for label, token in SERVICE_TOKENS.items():
            if ext.get(f"Organization provides {label}"):
                org["tokens"].add(token)
    if skipped:
        print(f"lsa: skipped {skipped} placemarks without resolvable name/state")

    source_id = write_source(
        "lsa", "member-network-map",
        kind="directory", publisher="Lutheran Services in America",
        title="LSA Member Network Map (our-network page embedded map, KML export)",
        url=PAGE_URL, tier="primary",
    )

    records = []
    for name, org in orgs.items():
        # file under the state with the most listed locations (ties: a-z)
        state = sorted(org["states"].items(), key=lambda kv: (-kv[1], kv[0]))[0][0]
        rec = {
            "_state": state, "_place_slug": "", "_name": name,
            "categories": ["family-support"] + sorted(org["tokens"]),
            "parent_org": "us/lutheran-services-in-america",
        }
        if len(org["rows"]) == 1 and org["rows"][0]["city"]:
            row = org["rows"][0]
            addr = {"city": row["city"], "state": row["state"]}
            if row["street"]:
                addr = {"street": row["street"], **addr}
            rec["address"] = Flow(addr)
            geoid, _ = places.resolve(row["state"], row["city"])
            if geoid:
                rec["place"] = geoid
        if org["website"]:
            rec["website"] = ensure_https(org["website"])
        rec["sources"] = [source_id]
        rec["verified"] = Flow(on=today(), method="scrape")
        records.append(rec)

    n_members = len(records)
    records.append({
        "_state": "us", "_place_slug": "",
        "_name": "Lutheran Services in America",
        "id": "us/lutheran-services-in-america",
        "aliases": ["LSA"],
        "categories": ["family-support"],
        "description": "National network of some 300 Lutheran health and human "
                       "services organizations — members provide senior services, "
                       "children and family services, disability services, "
                       "refugee services, housing, and health care.",
        "website": "https://lutheranservices.org",
        "service_area": Flow(kind="national"),
        "sources": [source_id],
        "verified": Flow(on=today(), method="scrape"),
    })

    if n_members < 200:
        raise SystemExit(f"lsa: only {n_members} member orgs — expected ~283; aborting")
    replace_records("orgs", source_id, records)


if __name__ == "__main__":
    main(sys.argv[1:])
