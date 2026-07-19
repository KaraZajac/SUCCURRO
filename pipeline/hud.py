"""HUD Resource Locator ArcGIS backend -> CoC org records + PHA site records.

Layer 8: Continuum of Care contacts (one row per CoC x contact type, polygon
service areas we don't need). One org per CoC; we keep org-level phone/email
from the primary-contact row and never publish contact-person names.
Layer 1: Public Housing Agencies (~3,483) as housing-assistance sites.
Keyless, federal public domain. Raw pages cached under sources/hud/.

Usage: python3 -m pipeline.hud [--force]
"""
import json
import sys

from .emit import Places, replace_records, today, write_source
from .util import Flow, SOURCES, fetch

QUERY = ("https://egis.hud.gov/arcgis/rest/services/hrl/HudResourceLocator/MapServer/"
         "{layer}/query?where=1%3D1&outFields=*&f=json&orderByFields=OBJECTID"
         "&returnGeometry={geom}&outSR=4326&resultRecordCount=1000&resultOffset={offset}")

PROGRAM_LABEL = {
    "Section 8": "Housing Choice Voucher (Section 8) agency",
    "Low-Rent": "Public housing (Low-Rent) agency",
    "Combined": "Public housing and Housing Choice Voucher agency",
}


def fetch_layer(layer, geom, force):
    features, offset, page = [], 0, 1
    while True:
        cache = SOURCES / "hud" / f"layer{layer}-p{page}.json"
        data = json.loads(fetch(QUERY.format(layer=layer, geom=geom, offset=offset),
                                cache, force=force).read_text())
        if "features" not in data:
            raise SystemExit(f"hud: unexpected payload on layer {layer}: {str(data)[:200]}")
        features.extend(data["features"])
        if not data.get("exceededTransferLimit") and len(data["features"]) < 1000:
            return features
        offset += len(data["features"])
        page += 1


def clean(value):
    return (value or "").strip()


def phone_fmt(raw):
    digits = "".join(c for c in (raw or "") if c.isdigit())
    if len(digits) == 10:
        return f"{digits[:3]}-{digits[3:6]}-{digits[6:]}"
    return clean(raw) or None


def coc_orgs(places, source_id, force):
    by_coc: dict[str, dict] = {}
    for feat in fetch_layer(8, "false", force):
        a = feat["attributes"]
        num = clean(a.get("COCNUM"))
        if not num:
            continue
        entry = by_coc.setdefault(num, {"name": clean(a.get("COCNAME"))})
        if clean(a.get("CONTACT_TYPE")) == "Primary Contact" or "phone" not in entry:
            entry["phone"] = phone_fmt(a.get("PRIMARY_PHONE"))
            entry["email"] = clean(a.get("EMAIL_ADDRESS")) or None

    records = []
    for num, entry in by_coc.items():
        state = num.split("-")[0].lower()
        if state not in places.by_state or not entry["name"]:
            continue
        rec = {
            "_state": state, "_place_slug": "", "_name": entry["name"],
            "categories": ["housing", "housing-assistance"],
            "description": "HUD Continuum of Care — coordinates homeless services for its region.",
            "service_area": Flow(kind="regional", name=entry["name"], state=state),
            "external_ids": Flow(coc=num),
        }
        if entry.get("phone"):
            rec["phone"] = entry["phone"]
        if entry.get("email"):
            rec["email"] = entry["email"]
        rec["sources"] = [source_id]
        rec["verified"] = Flow(on=today(), method="api")
        records.append(rec)
    if len(records) < 300:
        raise SystemExit(f"hud: only {len(records)} CoCs — expected ~384")
    return records


def pha_sites(places, source_id, force):
    records, seen = [], set()
    for feat in fetch_layer(1, "true", force):
        a = feat["attributes"]
        name = clean(a.get("FORMAL_PARTICIPANT_NAME")).title()
        state = clean(a.get("STD_ST")).lower()
        city = clean(a.get("STD_CITY"))
        if not name or state not in places.by_state:
            continue
        key = (name.lower(), city.lower())
        if key in seen:
            continue
        seen.add(key)
        geoid, place_slug = places.resolve(state, city)
        rec = {
            "_state": state, "_place_slug": place_slug, "_name": name,
            "categories": ["housing-assistance"],
            "address": Flow({k: v for k, v in {
                "street": clean(a.get("STD_ADDR")) or None, "city": city,
                "state": state, "zip": clean(a.get("STD_ZIP5")) or None,
            }.items() if v}),
        }
        label = PROGRAM_LABEL.get(clean(a.get("HA_PROGRAM_TYPE")))
        if label:
            rec["description"] = label
        if geoid:
            rec["place"] = geoid
        geom = feat.get("geometry") or {}
        if isinstance(geom.get("y"), (int, float)) and abs(geom["y"]) <= 90:
            rec["geo"] = Flow(lat=round(geom["y"], 5), lng=round(geom["x"], 5))
        if phone_fmt(a.get("HA_PHN_NUM")):
            rec["phone"] = phone_fmt(a.get("HA_PHN_NUM"))
        rec["sources"] = [source_id]
        rec["verified"] = Flow(on=today(), method="api")
        records.append(rec)
    if len(records) < 2500:
        raise SystemExit(f"hud: only {len(records)} PHAs — expected ~3,400")
    return records


def main(argv):
    force = "--force" in argv
    places = Places()
    source_id = write_source(
        "hud", "resource-locator",
        kind="dataset", publisher="US Department of Housing and Urban Development",
        title="HUD Resource Locator (CoC contacts and Public Housing Agencies)",
        url="https://resources.hud.gov/", tier="primary",
    )
    replace_records("orgs", source_id, coc_orgs(places, source_id, force))
    replace_records("sites", source_id, pha_sites(places, source_id, force))


if __name__ == "__main__":
    main(sys.argv[1:])
