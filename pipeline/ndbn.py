"""National Diaper Bank Network member directory -> org records (diaper-bank).

The member map is a Google My Maps; its KML export lists every member as a
Placemark. Most placemarks (~230 of 250) carry no Point coordinates, but every
description holds 'Key:: value' pairs — Member ID, City (Headquarters), State,
Website — so state/city come from the description (like pflag), with the
coordinate + Places().nearest() path as fallback for placemarks whose
description lacks a usable state. Raw KML cached under sources/ndbn/.
Facts-only re-expression, attributed (see DATA-RIGHTS.md).

Usage: python3 -m pipeline.ndbn [--force]
"""
import sys
import xml.etree.ElementTree as ET

from .emit import Places, replace_records, today, write_source
from .util import Flow, SOURCES, fetch

KML_URL = "https://www.google.com/maps/d/kml?mid=1nqyZcnNPL_M0fXbaILWlmZVg6TU&forcekml=1"
NS = "{http://www.opengis.net/kml/2.2}"

# a handful of placemarks spell the state out ("Wisconsin") instead of the code
STATE_NAMES = {
    "alabama": "al", "alaska": "ak", "arizona": "az", "arkansas": "ar",
    "california": "ca", "colorado": "co", "connecticut": "ct", "delaware": "de",
    "district of columbia": "dc", "florida": "fl", "georgia": "ga", "hawaii": "hi",
    "idaho": "id", "illinois": "il", "indiana": "in", "iowa": "ia", "kansas": "ks",
    "kentucky": "ky", "louisiana": "la", "maine": "me", "maryland": "md",
    "massachusetts": "ma", "michigan": "mi", "minnesota": "mn", "mississippi": "ms",
    "missouri": "mo", "montana": "mt", "nebraska": "ne", "nevada": "nv",
    "new hampshire": "nh", "new jersey": "nj", "new mexico": "nm", "new york": "ny",
    "north carolina": "nc", "north dakota": "nd", "ohio": "oh", "oklahoma": "ok",
    "oregon": "or", "pennsylvania": "pa", "puerto rico": "pr", "rhode island": "ri",
    "south carolina": "sc", "south dakota": "sd", "tennessee": "tn", "texas": "tx",
    "utah": "ut", "vermont": "vt", "virginia": "va", "washington": "wa",
    "west virginia": "wv", "wisconsin": "wi", "wyoming": "wy",
}


def parse_description(desc: str) -> dict:
    """'Member ID:: 12001<br>City (Headquarters):: Hyannis<br>State:: MA<br>...'
    -> {key: value}. Single-colon lines (e.g. 'Link to Volunteer:') don't match."""
    fields = {}
    for part in desc.split("<br>"):
        key, sep, value = part.partition("::")
        if sep:
            fields[key.strip()] = value.strip()
    return fields


def parse_point(pm) -> tuple[float, float] | None:
    """KML coordinates are 'lng,lat,alt'."""
    text = pm.findtext(f".//{NS}Point/{NS}coordinates") or ""
    try:
        lng, lat = text.strip().split(",")[:2]
        return round(float(lat), 5), round(float(lng), 5)
    except ValueError:
        return None


def norm_url(raw: str) -> str:
    raw = raw.strip()
    return raw if "://" in raw else f"https://{raw}"


def main(argv):
    force = "--force" in argv
    places = Places()
    cache = SOURCES / "ndbn" / "member-directory.kml"
    root = ET.parse(fetch(KML_URL, cache, force=force)).getroot()

    source_id = write_source(
        "ndbn", "member-directory",
        kind="directory", publisher="National Diaper Bank Network",
        title="NDBN member directory map",
        url="https://nationaldiaperbanknetwork.org/member-directory/", tier="primary",
    )

    records = []
    for pm in root.iter(f"{NS}Placemark"):
        name = (pm.findtext(f"{NS}name") or "").strip()
        if not name:
            continue
        fields = parse_description(pm.findtext(f"{NS}description") or "")
        city = fields.get("City (Headquarters)", "")
        st = fields.get("State", "").lower()
        st = STATE_NAMES.get(st, st)
        latlng = parse_point(pm)
        if st in places.by_state:
            geoid, _ = places.resolve(st, city)
        elif latlng:
            near = places.nearest(*latlng)
            if near is None:
                continue
            st, geoid, _ = near
        else:
            continue
        rec = {
            "_state": st, "_place_slug": "", "_name": name,
            "categories": ["diaper-bank"],
            "parent_org": "us/national-diaper-bank-network",
        }
        if city:
            rec["address"] = Flow(city=city, state=st)
        if geoid:
            rec["place"] = geoid
        if latlng:
            rec["geo"] = Flow(lat=latlng[0], lng=latlng[1])
        if fields.get("Website"):
            rec["website"] = norm_url(fields["Website"])
        if fields.get("Member ID"):
            rec["external_ids"] = Flow(ndbn=fields["Member ID"])
        rec["sources"] = [source_id]
        rec["verified"] = Flow(on=today(), method="scrape")
        records.append(rec)

    if len(records) < 150:
        raise SystemExit(f"ndbn: only {len(records)} members — expected ~250; aborting")

    # the national umbrella org the member banks point at
    records.append({
        "_state": "us", "_place_slug": "", "_name": "National Diaper Bank Network",
        "id": "us/national-diaper-bank-network",
        "categories": ["diaper-bank"],
        "website": "https://nationaldiaperbanknetwork.org",
        "service_area": Flow(kind="national"),
        "sources": [source_id],
        "verified": Flow(on=today(), method="scrape"),
    })

    replace_records("orgs", source_id, records)


if __name__ == "__main__":
    main(sys.argv[1:])
