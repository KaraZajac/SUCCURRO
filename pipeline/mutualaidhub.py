"""Mutual Aid Hub (Town Hall Project) -> mutual-aid org + food-resource site records.

Publicly readable Firestore REST collections, PDDL 1.0 (public-domain dedication).
Largely COVID-era data whose liveness is unverified, so every record is marked
provisional. DATA-RIGHTS flags this endpoint fragile — raw pages are snapshotted
under sources/mutualaidhub/.

Usage: python3 -m pipeline.mutualaidhub [--force]
"""
import json
import sys

from .emit import Places, replace_records, today, write_source
from .util import Flow, SOURCES, fetch

BASE = ("https://firestore.googleapis.com/v1/projects/townhallproject-86312/"
        "databases/(default)/documents/{collection}?pageSize=300{token}")

RESOURCE_CATEGORIES = {
    "fridge": "community-fridge", "freezer": "community-fridge",
    "pantry": "food-pantry", "foodBank": "food-bank",
}


def decode(value):
    """Collapse a Firestore typed value to a plain Python value."""
    for kind, raw in value.items():
        if kind == "arrayValue":
            return [decode(v) for v in raw.get("values", [])]
        if kind == "mapValue":
            return {k: decode(v) for k, v in raw.get("fields", {}).items()}
        if kind == "doubleValue":
            return float(raw)
        if kind == "integerValue":
            return int(raw)
        return raw
    return None


def fetch_collection(collection, force):
    docs, token, page = [], "", 1
    while True:
        cache = SOURCES / "mutualaidhub" / f"{collection}-p{page}.json"
        url = BASE.format(collection=collection,
                          token=f"&pageToken={token}" if token else "")
        data = json.loads(fetch(url, cache, force=force).read_text())
        for doc in data.get("documents", []):
            docs.append({k: decode(v) for k, v in doc.get("fields", {}).items()})
        token = data.get("nextPageToken")
        page += 1
        if not token:
            return docs


def base_record(doc, places, source_id):
    state = (doc.get("state") or "").strip().lower()
    if state not in places.by_state:
        return None
    city = (doc.get("city") or "").strip()
    geoid, place_slug = places.resolve(state, city)
    lat, lng = doc.get("lat"), doc.get("lng")
    if geoid is None and isinstance(lat, float) and isinstance(lng, float):
        near = places.nearest(lat, lng)
        if near and near[0] == state:
            _, geoid, place_slug = near
    rec = {"_state": state, "_place_slug": place_slug}
    if geoid:
        rec["place"] = geoid
    if isinstance(lat, float) and isinstance(lng, float) and (lat, lng) != (0.0, 0.0):
        rec["geo"] = Flow(lat=round(lat, 5), lng=round(lng, 5))
    website = (doc.get("website") or "").strip()
    if website.startswith("http"):
        rec["website"] = website
    rec["provisional"] = True
    rec["sources"] = [source_id]
    rec["verified"] = Flow(on=today(), method="api")
    return rec


def main(argv):
    force = "--force" in argv
    places = Places()
    source_id = write_source(
        "mutualaidhub", "firestore",
        kind="directory", publisher="Mutual Aid Hub (Town Hall Project)",
        title="Mutual Aid Hub network and food resource map",
        url="https://www.mutualaidhub.org/", tier="secondary",
        notes="PDDL 1.0; largely COVID-era records, liveness unverified (provisional).",
    )

    orgs = []
    for doc in fetch_collection("mutual_aid_networks", force):
        name = (doc.get("title") or doc.get("name") or "").strip()
        rec = base_record(doc, places, source_id)
        if not name or rec is None:
            continue
        orgs.append({**rec, "_name": name, "categories": ["mutual-aid"]})
    if len(orgs) < 500:
        raise SystemExit(f"mutualaidhub: only {len(orgs)} networks — collection changed?")

    sites = []
    for doc in fetch_collection("food_resources", force):
        name = (doc.get("title") or doc.get("name") or doc.get("organization") or "").strip()
        rec = base_record(doc, places, source_id)
        if rec is None:
            continue
        resources = doc.get("resources") or {}
        cats = sorted({tok for key, tok in RESOURCE_CATEGORIES.items() if resources.get(key)})
        if not name:
            name = "Community food resource"
        sites.append({**rec, "_name": name, "categories": cats or ["food-pantry"]})

    replace_records("orgs", source_id, orgs)
    replace_records("sites", source_id, sites)


if __name__ == "__main__":
    main(sys.argv[1:])
