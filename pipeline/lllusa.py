"""La Leche League USA group map -> org records (breastfeeding/parenting
peer support; family-support / peer-support).

The find-a-group map runs WP Go Maps (wpgmza); its open REST markers endpoint
returns every group in one GET (~396 markers: title, free-text address,
lat/lng, link). Addresses are inconsistent — "Palmer, AK 99645",
"Corona, California 92879, USA", "Hoboken NJ 07030", and occasionally a
street line — so parsing is best-effort with a nearest-place fallback from
the coordinate. Many groups are online/Facebook-first; they are kept, with
the group link as website. Marker descriptions are leader-contact prose
(personal names/emails) and are not copied. Facts-only re-expression,
attributed (see DATA-RIGHTS.md).

Usage: python3 -m pipeline.lllusa [--force]
"""
import json
import re
import sys
from collections import Counter

from .emit import Places, replace_records, today, write_source
from .util import Flow, SOURCES, fetch

URL = "https://lllusa.org/wp-json/wpgmza/v1/markers?filter={}"
MAP_PAGE = "https://lllusa.org/find-local-support/"

ZIP_RE = re.compile(r"^\d{5}(-\d{4})?$")
TAIL_RE = re.compile(r"^(?P<st>[A-Za-z][A-Za-z. ]*?)\.?\s*(?P<zip>\d{5}(-\d{4})?)?$")
ONE_PART_RE = re.compile(r"^(?P<city>.+?)\s+(?P<st>[A-Za-z]{2})\.?\s+(?P<zip>\d{5}(-\d{4})?)$")

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
    "puerto rico": "pr", "guam": "gu", "virgin islands": "vi",
}
US_STATE_CODES = set(STATE_NAMES.values()) | {"dc"}


def state_code(raw: str) -> str:
    raw = (raw or "").strip().rstrip(".").lower()
    if len(raw) == 2:
        return raw if raw in US_STATE_CODES else ""
    return STATE_NAMES.get(raw, "")


def parse_address(raw: str) -> dict:
    """Best-effort {street?, city, state, zip?} from the marker's free-text
    address; {} when no US state can be derived."""
    parts = [p.strip() for p in raw.split(",")
             if p.strip() and p.strip().rstrip(".").lower()
             not in ("usa", "united states", "us", "ee. uu", "ee uu")]
    if not parts:
        return {}
    m = TAIL_RE.match(parts[-1])
    if m and state_code(m["st"]):
        addr = {"state": state_code(m["st"])}
        if m["zip"]:
            addr["zip"] = m["zip"]
        if len(parts) >= 2:
            addr["city"] = parts[-2]
        if len(parts) >= 3:
            addr = {"street": ", ".join(parts[:-2]), **addr}
        return addr if "city" in addr else {}
    m = ONE_PART_RE.match(parts[-1])
    if m and state_code(m["st"]):
        addr = {"city": m["city"], "state": state_code(m["st"]), "zip": m["zip"]}
        if len(parts) >= 2:
            addr = {"street": ", ".join(parts[:-1]), **addr}
        return addr
    return {}


def clean_website(link: str) -> str:
    link = (link or "").strip()
    if not link:
        return ""
    if link.startswith("//"):
        return "https:" + link
    if not re.match(r"https?://", link, re.I):
        return "https://" + link
    return link


def main(argv):
    force = "--force" in argv
    places = Places()
    cache = SOURCES / "lllusa" / "markers.json"
    markers = json.loads(fetch(URL, cache, force=force).read_text())
    if len(markers) < 300:
        raise SystemExit(f"lllusa: only {len(markers)} markers — expected ~396")

    source_id = write_source(
        "lllusa", "group-map",
        kind="api-feed", publisher="La Leche League USA",
        title="LLL USA find-local-support map (WP Go Maps markers API)",
        url=MAP_PAGE, tier="primary",
    )

    records, skipped, got = [], Counter(), Counter()
    for mk in markers:
        name = (mk.get("title") or "").strip()
        if not name:
            skipped["no-title"] += 1
            continue
        try:
            lat, lng = round(float(mk["lat"]), 5), round(float(mk["lng"]), 5)
        except (KeyError, TypeError, ValueError):
            lat = lng = None

        addr = parse_address(mk.get("address") or "")
        st = addr.get("state", "")
        if not st and lat is not None:
            near = places.nearest(lat, lng)
            if near:
                st = near[0]
                got["state-from-geo"] += 1
        if not st:
            skipped["no-state"] += 1
            continue

        rec = {
            "_state": st, "_place_slug": "", "_name": name,
            "categories": ["family-support", "peer-support"],
            "parent_org": "us/la-leche-league-usa",
        }
        if addr.get("zip") and not ZIP_RE.match(addr["zip"]):
            del addr["zip"]
        if addr:
            rec["address"] = Flow(addr)
            got["address"] += 1
            geoid, _ = places.resolve(st, addr.get("city", ""))
            if geoid:
                rec["place"] = geoid
                got["place"] += 1
        if lat is not None:
            rec["geo"] = Flow(lat=lat, lng=lng)
            got["geo"] += 1
        website = clean_website(mk.get("link"))
        if website:
            rec["website"] = website
            got["website"] += 1
        if mk.get("id"):
            rec["external_ids"] = Flow(wpgmza=str(mk["id"]))
        rec["sources"] = [source_id]
        rec["verified"] = Flow(on=today(), method="api")
        records.append(rec)

    if skipped:
        print("skipped:", dict(skipped))
    for field in ("address", "place", "geo", "website", "state-from-geo"):
        print(f"enriched {got[field]}/{len(records)} groups with {field}")
    if len(records) < 300:
        raise SystemExit(f"lllusa: only {len(records)} US groups — expected ~390")

    records.append({
        "_state": "us", "_place_slug": "", "_name": "La Leche League USA",
        "id": "us/la-leche-league-usa",
        "categories": ["family-support", "peer-support"],
        "description": "Breastfeeding/chestfeeding information and peer "
                       "support — local groups hold free meetings led by "
                       "accredited Leaders; many meet online.",
        "website": "https://lllusa.org",
        "service_area": Flow(kind="national"),
        "sources": [source_id],
        "verified": Flow(on=today(), method="api"),
    })

    replace_records("orgs", source_id, records)


if __name__ == "__main__":
    main(sys.argv[1:])
