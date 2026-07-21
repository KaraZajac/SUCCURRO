"""Indian Health Service Find Health Care facilities -> site records (health).

Authoritative source: ihs.gov/findhealthcare redirects to an ArcGIS Experience
app whose only data source is the IHS-org-hosted feature layer
ITU_Health_Facilities_View (services2.arcgis.com/VFLAJVozK0rtzQmT) — every IHS,
tribal (Title 1 / Title 5 638 / self-governance), and urban Indian health
facility (~1,150 rows, all Active). One unauthenticated query returns the whole
layer (maxRecordCount 2000 > row count; a resultOffset pager guards growth).
Federal public domain. Cached under sources/ihs/.

Categories: everything is health; SERVICE_TYPE adds su-treatment where it names
substance-use-disorder treatment (incl. Youth Regional Treatment Centers, which
are IHS youth SUD facilities) and mh-treatment where it names behavioral health.
FHC_Facility_Type/BH_FLAG are looser facility-level markers and are deliberately
not mapped — SERVICE_TYPE is the per-site service designation. Skipped: pure
administration and staff-housing rows (not service delivery).

Quirks: ASUFAC codes are shared by co-administered sub-facilities (a clinic and
its behavioral-health branch), so identity is (name, street, city) and asufac is
kept as a non-unique external id. HOURS is freeform prose and is not parsed.

Usage: python3 -m pipeline.ihs [--force]
"""
import json
import re
import sys
from urllib.parse import urlencode

from .emit import Places, replace_records, today, write_source
from .util import Flow, SOURCES, fetch

LAYER = ("https://services2.arcgis.com/VFLAJVozK0rtzQmT/arcgis/rest/services/"
         "ITU_Health_Facilities_View/FeatureServer/0")
FINDER = "https://www.ihs.gov/findhealthcare/"
CACHE = SOURCES / "ihs"

# SERVICE_TYPE values that are not service-delivery sites
SKIP_TYPES = {"Tribal Health Administration", "Clinical Staff Housing"}

_DOMAIN = re.compile(r"^[A-Za-z0-9-]+(\.[A-Za-z0-9-]+)+(/|$)")
ZIP_RE = re.compile(r"\d{5}(-\d{4})?")

# LOCATION_TYPE -> description prefix
OPERATOR = {
    "IHS": "IHS",
    "Title 1 Tribal": "Tribal",
    "Title 5 Tribal 638": "Tribal",
    "Self-Governance": "Tribal",
    "Urban": "Urban Indian",
}

# FHC_Facility_Type -> description noun ("Heallth Station" is an upstream typo)
FACILITY_NOUN = {
    "Health Center": "health center",
    "Hospital": "hospital",
    "Health Station": "health station",
    "Heallth Station": "health station",
    "Alaska Village Clinic": "village clinic",
    "Behavioral Health": "behavioral health facility",
    "Dental Clinic": "dental clinic",
}


def load_features(force: bool) -> list[dict]:
    """All layer rows (attributes only; LATITUDE/LONGITUDE are fields)."""
    feats, offset = [], 0
    while True:
        query = urlencode({
            "where": "1=1", "outFields": "*", "returnGeometry": "false",
            "orderByFields": "OBJECTID_1", "resultOffset": offset, "f": "json",
        })
        path = fetch(f"{LAYER}/query?{query}", CACHE / f"facilities-{offset}.json",
                     force=force)
        data = json.loads(path.read_bytes())
        if "features" not in data:
            raise SystemExit(f"ihs: layer query returned no features key: "
                             f"{str(data)[:200]}")
        feats.extend(f["attributes"] for f in data["features"])
        if not data.get("exceededTransferLimit"):
            return feats
        offset = len(feats)


def norm_phone(raw: str) -> str | None:
    digits = re.sub(r"\D", "", raw or "")
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    if len(digits) == 10:
        return f"{digits[:3]}-{digits[3:6]}-{digits[6:]}"
    return None


def clean_website(raw: str) -> str | None:
    w = (raw or "").strip()
    m = re.match(r"^(https?)://(.+)", w, re.I)
    if m:
        return f"{m.group(1).lower()}://{m.group(2)}"
    if _DOMAIN.match(w):
        return f"https://{w}"
    return None


def categorize(service_type: str) -> list[str]:
    cats = ["health"]
    if ("Substance Use Disorder Treatment" in service_type
            or service_type == "Youth Regional Treatment Center"):
        cats.append("su-treatment")
    if "Behavioral Health" in service_type:
        cats.append("mh-treatment")
    return cats


def describe(location_type: str, fhc_type: str) -> str | None:
    prefix = OPERATOR.get((location_type or "").strip())
    noun = FACILITY_NOUN.get((fhc_type or "").strip(), "health facility")
    if not prefix:
        return None
    if prefix == "Urban Indian":
        return f"Urban Indian organization {noun}"
    return f"{prefix} {noun}"


def main(argv):
    force = "--force" in argv
    places = Places()
    source_id = write_source(
        "ihs", "find-health-care",
        kind="api-feed", publisher="Indian Health Service",
        title="IHS Find Health Care facility layer (ITU_Health_Facilities_View)",
        url=f"{LAYER}/query", tier="primary",
        notes=f"Feature layer behind the {FINDER} locator app; federal public domain.",
    )

    feats = load_features(force)
    if len(feats) < 300:
        raise SystemExit(f"ihs: layer returned {len(feats)} rows — expected "
                         "1,000+; API shape changed?")

    records, seen = [], set()
    skipped_type = skipped_state = skipped_inactive = 0
    for a in feats:
        name = (a.get("FACILITY_NAME") or "").strip()
        if not name:
            continue
        status = (a.get("STATUS") or "").strip()
        if status and status != "Active":
            skipped_inactive += 1
            continue
        stype = (a.get("SERVICE_TYPE") or "").strip()
        if stype in SKIP_TYPES:
            skipped_type += 1
            continue
        st = (a.get("STATE") or "").strip().lower()
        if st not in places.by_state:
            skipped_state += 1
            continue
        city = (a.get("CITY") or "").strip()
        street = (a.get("PHYSICAL_STREET") or "").strip()
        key = (name.lower(), street.lower(), city.lower())
        if key in seen:
            continue
        seen.add(key)

        geoid, place_slug = places.resolve(st, city)
        rec = {
            "_state": st, "_place_slug": place_slug, "_name": name,
            "categories": categorize(stype),
        }
        desc = describe(a.get("LOCATION_TYPE"), a.get("FHC_Facility_Type"))
        if desc:
            rec["description"] = desc
        addr = {}
        if street:
            addr["street"] = street
        if city:
            addr["city"] = city
            addr["state"] = st
            zip_code = (a.get("ZIP") or "").strip()
            if ZIP_RE.fullmatch(zip_code):
                addr["zip"] = zip_code
            rec["address"] = Flow(addr)
        try:
            lat, lng = float(a["LATITUDE"]), float(a["LONGITUDE"])
            if 15 <= lat <= 72 and -180 <= lng <= -60:
                rec["geo"] = Flow(lat=round(lat, 5), lng=round(lng, 5))
        except (KeyError, TypeError, ValueError):
            pass
        if not geoid and "geo" in rec:
            near = places.nearest(rec["geo"]["lat"], rec["geo"]["lng"])
            if near and near[0] == st:  # state-matched nearest fallback
                geoid = near[1]
        if geoid:
            rec["place"] = geoid
        phone = norm_phone(a.get("PHONE"))
        if phone:
            rec["phone"] = phone
        website = clean_website(a.get("WEBSITE_URL"))
        if website:
            rec["website"] = website
        services = [s.strip() for s in (a.get("SERVICES") or "").split(",")
                    if s.strip()]
        if stype and stype not in services:
            services.insert(0, stype)
        if services:
            rec["services"] = services
        asufac = (a.get("ASUFAC") or "").strip()
        if asufac:
            rec["external_ids"] = Flow(asufac=asufac)
        rec["sources"] = [source_id]
        rec["verified"] = Flow(on=today(), method="api")
        records.append(rec)

    print(f"kept {len(records)} facilities from {len(feats)} rows "
          f"(skipped: {skipped_type} admin/housing, {skipped_state} outside "
          f"place registry, {skipped_inactive} inactive)")
    if len(records) < 300:
        raise SystemExit(f"ihs: only {len(records)} site records — expected "
                         "1,000+; aborting")

    replace_records("sites", source_id, records)


if __name__ == "__main__":
    main(sys.argv[1:])
