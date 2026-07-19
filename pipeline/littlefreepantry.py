"""Little Free Pantry map -> site records (food-pantry).

The map page embeds every pantry as `pantries.push({lat, lng, id, name})` lines —
one GET. Coordinates only, so state/place come from Places.nearest(). Per
DATA-RIGHTS we take pantry facts only (name, coordinates) and never the
submitter contact fields shown on detail pages.

Usage: python3 -m pipeline.littlefreepantry [--force]
"""
import html as htmllib
import re
import sys

from .emit import Places, replace_records, today, write_source
from .util import Flow, SOURCES, fetch

URL = "https://mapping.littlefreepantry.org/"
PUSH_RE = re.compile(
    r"pantries\.push\(\{\s*lat:\s*(-?[\d.]+),\s*lng:\s*(-?[\d.]+),"
    r"\s*id:\s*(\d+),\s*name:\s*\"(.*?)\"\s*\}\)")


def main(argv):
    force = "--force" in argv
    places = Places()
    page = fetch(URL, SOURCES / "littlefreepantry" / "map.html", force=force).read_text()
    matches = PUSH_RE.findall(page)
    if len(matches) < 3000:
        raise SystemExit(f"littlefreepantry: only {len(matches)} pantries — page layout changed?")

    source_id = write_source(
        "littlefreepantry", "map",
        kind="directory", publisher="Little Free Pantry",
        title="Little Free Pantry map",
        url=URL, tier="primary",
    )

    records, seen = [], set()
    skipped = 0
    for lat_s, lng_s, pid, raw_name in matches:
        lat, lng = float(lat_s), float(lng_s)
        name = htmllib.unescape(raw_name).strip()
        if not name or pid in seen:
            continue
        seen.add(pid)
        near = places.nearest(lat, lng)
        if not near:
            skipped += 1
            continue
        state, geoid, place_slug = near
        records.append({
            "_state": state, "_place_slug": place_slug, "_name": name,
            "categories": ["food-pantry"],
            "place": geoid,
            "geo": Flow(lat=round(lat, 5), lng=round(lng, 5)),
            "external_ids": Flow(lfp=pid),
            "sources": [source_id],
            "verified": Flow(on=today(), method="scrape"),
        })
    if skipped:
        print(f"skipped {skipped} pantries with no nearby registry place (non-US or offshore)")

    replace_records("sites", source_id, records)


if __name__ == "__main__":
    main(sys.argv[1:])
