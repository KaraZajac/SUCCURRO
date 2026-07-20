"""ZIP (ZCTA) centroids -> data/crosswalk/zips.yaml, for search-by-ZIP.

Census ZCTA gazetteer, same format/family as the place registry. The site
resolves a ZIP's centroid to the nearest served community at build time, so
this stays a pure geo table (~33k entries). Public domain.

Usage: python3 -m pipeline.zips [--year 2025] [--force]
"""
import sys

from .places import read_gazetteer
from .util import DATA, dump_yaml


def main(argv):
    year = 2025
    force = "--force" in argv
    if "--year" in argv:
        year = int(argv[argv.index("--year") + 1])
    zips = {}
    for row in read_gazetteer(year, "zcta", force):
        try:
            zips[row["GEOID"]] = [round(float(row["INTPTLAT"]), 4),
                                  round(float(row["INTPTLONG"]), 4)]
        except (KeyError, ValueError):
            continue
    if len(zips) < 30000:
        raise SystemExit(f"zips: only {len(zips)} ZCTAs — expected ~33k")
    dump_yaml(zips, DATA / "crosswalk" / "zips.yaml")
    print(f"wrote {len(zips)} ZCTA centroids -> data/crosswalk/zips.yaml")


if __name__ == "__main__":
    main(sys.argv[1:])
