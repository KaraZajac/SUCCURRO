"""LSC grantee office locations (ArcGIS feature service) -> site records (legal-aid).

pipeline.lsc covers the 129 grantee programs as orgs; this module adds the
office level. LSC's Find Legal Aid Programs.json has no office layer and no
companion Offices.json exists, but LSC's GIS account (laytonj_LSCGOV) publishes
"LSC_offices_grantees_main_branch (Public)" on ArcGIS Online — per its own
description "LSC's official spatial file of LSC grantee main and branch
offices" — as a public feature service: 860 point features with office name,
type (Main/Branch), grantee legal name, street/suite/city/state/zip, lat/lng,
and a stable recipOffID. No phone/website at office level (omit-absent).
Caveat: the service's dataLastEditDate is 2020-06-15, so office rosters of
grantees merged or defunded since then appear under their 2020 names; noted on
the source record.

Office records link `org:` to the pipeline.lsc grantee org when the 2020
orgName normalizes to exactly one current grantee name (corporate suffixes
ignored); offices of renamed/merged grantees stay orgless (site.org optional).
Skipped: territory offices outside the place registry (VI/GU/AS/MP) and blank
join artifacts. Duplicated recipOffIDs (spatial-join artifacts) dedupe first
row wins.

Rights: item access PUBLIC, licenseInfo "PUBLIC", published by LSC itself.
Facts-only re-expression, attributed.

Usage: python3 -m pipeline.lscoffices [--force]
"""
import json
import re
import sys

from .emit import Places, replace_records, today, write_source
from .util import DATA, Flow, SOURCES, fetch, load_yaml

ITEM_URL = "https://www.arcgis.com/home/item.html?id=af45e92323284d97ac48d75dc7143576"
SERVICE_URL = ("https://services3.arcgis.com/n7h3cEoHTyNCwjCf/arcgis/rest/services/"
               "LSC_offices_grantees_main_branch_(Public)/FeatureServer/0/query")
CACHE = SOURCES / "lsc"
PAGE = 1000  # layer maxRecordCount

GRANTEE_SOURCE = "lsc/grantee-programs"
# corporate boilerplate ignored in the loose name-match pass
STOPWORDS = {"inc", "incorporated", "corp", "corporation", "llc", "the", "of"}

ZIP_RE = re.compile(r"\d{5}(-\d{4})?")


def norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", text.lower())


def norm_loose(text: str) -> str:
    words = re.sub(r"[^a-z0-9 ]", "", text.lower()).split()
    return "".join(w for w in words if w not in STOPWORDS)


def grantee_index() -> tuple[dict[str, str], dict[str, str]]:
    """Two name indexes over the pipeline.lsc grantee orgs: exact-normalized
    and suffix-stripped. Keys matching multiple orgs are dropped (ambiguous)."""
    exact: dict[str, list] = {}
    loose: dict[str, list] = {}
    for path in sorted((DATA / "orgs").rglob("*.yaml")):
        rec = load_yaml(path)
        if GRANTEE_SOURCE in (rec.get("sources") or []):
            exact.setdefault(norm(rec["name"]), []).append(rec["id"])
            loose.setdefault(norm_loose(rec["name"]), []).append(rec["id"])
    return ({k: v[0] for k, v in exact.items() if len(v) == 1},
            {k: v[0] for k, v in loose.items() if len(v) == 1})


def fix_case(name: str) -> str:
    name = name.strip()
    return name.title() if name.isupper() or name.islower() else name


def load_features(force: bool) -> list[dict]:
    features, offset = [], 0
    while True:
        url = (f"{SERVICE_URL}?where=1%3D1&outFields=*&f=json"
               f"&resultOffset={offset}&resultRecordCount={PAGE}")
        path = fetch(url, CACHE / f"offices-p{offset // PAGE}.json", force=force)
        data = json.loads(path.read_bytes())
        if "error" in data or "features" not in data:
            raise SystemExit(f"lscoffices: query error at offset {offset}: "
                             f"{str(data)[:200]}")
        features.extend(data["features"])
        if not data.get("exceededTransferLimit"):
            return features
        offset += PAGE


def main(argv):
    force = "--force" in argv
    places = Places()
    exact, loose = grantee_index()
    source_id = write_source(
        "lsc", "office-locations",
        kind="dataset", publisher="Legal Services Corporation",
        title="LSC grantee main and branch office locations (ArcGIS feature service)",
        url=ITEM_URL, tier="primary",
        notes="Public feature service published by LSC's GIS account "
              "(laytonj_LSCGOV); item describes it as LSC's official spatial "
              f"file of grantee main and branch offices. Queried via {SERVICE_URL}. "
              "Service dataLastEditDate is 2020-06-15 — offices of grantees "
              "merged or renamed since then carry their 2020 program names.",
    )

    features = load_features(force)
    records, seen = [], set()
    skipped_blank = skipped_state = dup = matched = unmatched_offices = 0
    unmatched_orgs = set()
    for feat in features:
        at = feat["attributes"]
        name = fix_case(at.get("officenam") or "")
        org_name = (at.get("orgName") or "").strip()
        if not name and not org_name:
            skipped_blank += 1  # blank spatial-join artifact rows
            continue
        off_id = (at.get("recipOffID") or "").strip()
        if off_id and off_id in seen:
            dup += 1
            continue
        st = (at.get("State") or "").strip().lower()
        if st not in places.by_state:
            skipped_state += 1
            continue
        if off_id:
            seen.add(off_id)

        otype = (at.get("officetype") or "").strip().lower()
        rec = {
            "_state": st, "_place_slug": "", "_name": name or f"{org_name} office",
            "categories": ["legal-aid"],
        }
        if org_name:
            kind = f"{otype} office" if otype in ("main", "branch") else "office"
            rec["description"] = f"LSC-funded legal aid {kind} of {org_name}"
            org_id = exact.get(norm(org_name)) or loose.get(norm_loose(org_name))
            if org_id:
                rec["org"] = org_id
                matched += 1
            else:
                unmatched_offices += 1
                unmatched_orgs.add(org_name)

        city = fix_case(at.get("City") or "")
        geoid, place_slug = places.resolve(st, city)
        rec["_place_slug"] = place_slug
        addr = {}
        street = (at.get("address") or "").strip()
        suite = (at.get("bldgSuite") or "").strip()
        if street:
            addr["street"] = street
        if suite:
            addr["street2"] = suite
        if city:
            addr["city"] = city
            addr["state"] = st
            zip_code = (at.get("ZIP") or "").strip()
            if ZIP_RE.fullmatch(zip_code):
                addr["zip"] = zip_code
            rec["address"] = Flow(addr)
        try:
            lat, lng = float(at["Latitude"]), float(at["Longitude"])
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
        if off_id:
            rec["external_ids"] = Flow(lsc_office=off_id)
        rec["sources"] = [source_id]
        rec["verified"] = Flow(on=today(), method="api")
        records.append(rec)

    linked = matched + unmatched_offices
    print(f"kept {len(records)} offices of {len(features)} features "
          f"(skipped: {skipped_blank} blank rows, {skipped_state} outside place "
          f"registry; {dup} duplicate office ids); org FK matched {matched}/{linked}"
          + (f"; unmatched grantee names: {', '.join(sorted(unmatched_orgs))}"
             if unmatched_orgs else ""))
    if len(records) < 400:
        raise SystemExit(f"lscoffices: only {len(records)} offices — expected 400+; aborting")

    replace_records("sites", source_id, records)


if __name__ == "__main__":
    main(sys.argv[1:])
