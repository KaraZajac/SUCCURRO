"""Cross-cutting enrichment post-pass. Runs after modules (make build).

Two gap-fillers over data/sites and data/meetings, applied in place:
1. place assignment: records with geo but no place FK get the nearest
   registry place (state-matched) — fixes city-name variants like
   "Anchroage" that name-matching missed.
2. geocoding: site records with a street address but no geo are batched to
   the Census geocoder (free, public domain). Results are cached in
   sources/geocode/cache.json keyed by normalized address, so re-runs and
   refreshes only geocode new addresses.

Deterministic given the cache; the cache itself is regenerable.

Usage: python3 -m pipeline.enrich [--no-geocode]
"""
import csv
import io
import json
import re
import sys
import uuid
from pathlib import Path
from urllib.request import Request, urlopen

from .emit import Places
from .util import DATA, SOURCES, UA, Flow, dump_yaml, load_yaml

GEOCODER = "https://geocoding.geo.census.gov/geocoder/locations/addressbatch"
CACHE = SOURCES / "geocode" / "cache.json"
BATCH = 5000

_norm = re.compile(r"[^a-z0-9]+")


def addr_key(a):
    return "|".join(_norm.sub("", str(a.get(k, "")).lower())
                    for k in ("street", "city", "state", "zip"))


def geocode_batch(rows):
    """rows: list of (key, street, city, state, zip). Returns {key: (lat, lng)}."""
    body = io.StringIO()
    writer = csv.writer(body)
    for i, (key, street, city, state, zipc) in enumerate(rows):
        writer.writerow([i, street, city, state, zipc])
    boundary = uuid.uuid4().hex
    payload = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="addressFile"; filename="batch.csv"\r\n'
        f"Content-Type: text/csv\r\n\r\n{body.getvalue()}\r\n"
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="benchmark"\r\n\r\nPublic_AR_Current\r\n'
        f"--{boundary}--\r\n"
    ).encode()
    req = Request(GEOCODER, data=payload, headers={
        "User-Agent": UA,
        "Content-Type": f"multipart/form-data; boundary={boundary}",
    })
    with urlopen(req, timeout=600) as resp:
        text = resp.read().decode("utf-8", "replace")
    out = {}
    for line in csv.reader(io.StringIO(text)):
        if len(line) < 6 or line[2] != "Match":
            continue
        idx = int(line[0])
        lng, lat = line[5].split(",")
        out[rows[idx][0]] = (round(float(lat), 5), round(float(lng), 5))
    return out


def main(argv):
    do_geocode = "--no-geocode" not in argv
    places = Places()
    cache = json.loads(CACHE.read_text()) if CACHE.exists() else {}

    # pass 1: collect addresses needing geocoding (sites only; meetings carry
    # venue geo from their feeds or nothing meaningful to geocode)
    pending = {}
    if do_geocode:
        for path in sorted((DATA / "sites").rglob("*.yaml")):
            for rec in load_yaml(path) or []:
                a = rec.get("address") or {}
                if rec.get("geo") or not a.get("street") or not a.get("city"):
                    continue
                key = addr_key(a)
                if key not in cache:
                    pending[key] = (key, a["street"], a["city"],
                                    (a.get("state") or "").upper(), a.get("zip", ""))
        todo = list(pending.values())
        print(f"geocoding {len(todo)} new addresses (cache holds {len(cache)})")
        for i in range(0, len(todo), BATCH):
            chunk = todo[i:i + BATCH]
            results = geocode_batch(chunk)
            for key, _, _, _, _ in chunk:
                cache[key] = results.get(key)  # None = no match, cached too
            CACHE.parent.mkdir(parents=True, exist_ok=True)
            CACHE.write_text(json.dumps(cache))
            print(f"  batch {i // BATCH + 1}: {len(results)}/{len(chunk)} matched")

    # pass 2: apply geo from cache + nearest-place assignment
    geo_added = place_added = 0
    for kind in ("sites", "meetings"):
        for path in sorted((DATA / kind).rglob("*.yaml")):
            records = load_yaml(path) or []
            changed = False
            for rec in records:
                if kind == "sites" and not rec.get("geo"):
                    a = rec.get("address") or {}
                    hit = cache.get(addr_key(a)) if a.get("street") else None
                    if hit:
                        rec["geo"] = Flow(lat=hit[0], lng=hit[1])
                        geo_added += 1
                        changed = True
                if rec.get("geo") and not rec.get("place") and rec.get("format") != "online":
                    state = rec["id"].split("/")[0]
                    near = places.nearest(rec["geo"]["lat"], rec["geo"]["lng"])
                    if near and near[0] == state:
                        rec["place"] = near[1]
                        place_added += 1
                        changed = True
            if changed:
                dump_yaml(records, path)
    print(f"enrich: {geo_added} geo added, {place_added} place FKs assigned")


if __name__ == "__main__":
    main(sys.argv[1:])
