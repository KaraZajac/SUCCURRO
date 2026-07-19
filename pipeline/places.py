"""Build the national place registry from Census Bureau gazetteer files.

Places (incorporated places + CDPs) give city/town resolution nationwide; county
subdivisions cover the New England states where towns, not places, are the operative
municipal unit. Output: data/places/<state>.yaml, one list per state, sorted by slug.

Usage: python3 -m pipeline.places [--year 2025] [--force]
"""
import datetime
import sys
import zipfile
from collections import defaultdict

from .util import DATA, SOURCES, Flow, dump_yaml, fetch, load_yaml, slugify

GAZ = "https://www2.census.gov/geo/docs/maps-data/data/gazetteer/{y}_Gazetteer/{y}_Gaz_{kind}_national.zip"

# LSAD code -> kind token (subset that appears in place/cousub gazetteers)
LSAD_KIND = {
    "25": "city", "43": "town", "47": "village", "21": "borough",
    "57": "cdp", "44": "township", "45": "township", "46": "town",
    "37": "municipality", "00": "other",
}
# suffixes the NAME column appends per LSAD, to strip for display names
SUFFIXES = (
    " city", " town", " village", " borough", " CDP", " township",
    " municipality", " (balance)", " city (balance)",
)

# states where county subdivisions (towns) are the operative municipal layer
COUSUB_STATES = {"ct", "ma", "me", "nh", "ri", "vt"}


def clean_name(name: str) -> str:
    for suffix in SUFFIXES:
        if name.endswith(suffix):
            return name[: -len(suffix)]
    return name


def read_gazetteer(year: int, kind: str, force: bool) -> list[dict]:
    cache = SOURCES / "census" / f"{year}_gaz_{kind}_national.zip"
    fetch(GAZ.format(y=year, kind=kind), cache, force=force)
    with zipfile.ZipFile(cache) as z:
        names = [n for n in z.namelist() if n.endswith(".txt")]
        if len(names) != 1:
            raise SystemExit(f"expected exactly one .txt in {cache.name}, got {names}")
        text = z.read(names[0]).decode("utf-8", "replace")
    lines = text.splitlines()
    delim = "|" if "|" in lines[0] else "\t"  # Census switched tab -> pipe in 2025
    header = [h.strip() for h in lines[0].split(delim)]
    rows = []
    for line in lines[1:]:
        if not line.strip():
            continue
        rows.append(dict(zip(header, (v.strip() for v in line.split(delim)))))
    return rows


def build_records(rows: list[dict], kind_source: str) -> dict[str, list[dict]]:
    by_state: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        # keep active/consolidated governments, statistical entities (CDPs), and
        # nonfunctioning-but-real ones (Washington DC is coded N)
        if row.get("FUNCSTAT") not in ("A", "S", "B", "C", "N"):
            continue
        state = row["USPS"].lower()
        if kind_source == "cousubs" and state not in COUSUB_STATES:
            continue
        lsad = row.get("LSAD", "00")
        kind = LSAD_KIND.get(lsad, "other")
        if kind_source == "cousubs" and kind == "other":
            continue  # skip unorganized territories / undefined cousubs
        name = clean_name(row["NAME"])
        try:
            geo = Flow(lat=round(float(row["INTPTLAT"]), 5),
                       lng=round(float(row["INTPTLONG"]), 5))
        except (KeyError, ValueError):
            continue
        by_state[state].append({
            "id": row["GEOID"],
            "slug": slugify(name),
            "name": name,
            "state": state,
            "kind": kind,
            "geo": geo,
        })
    return by_state


def dedupe_slugs(records: list[dict]):
    seen: dict[str, int] = defaultdict(int)
    for rec in records:
        seen[rec["slug"]] += 1
    for rec in records:
        if seen[rec["slug"]] > 1:
            rec["slug"] = f"{rec['slug']}-{rec['id'][-4:]}"


def main(argv):
    year = 2025
    force = "--force" in argv
    if "--year" in argv:
        year = int(argv[argv.index("--year") + 1])

    by_state: dict[str, list[dict]] = defaultdict(list)
    for kind_source in ("place", "cousubs"):
        for state, recs in build_records(
                read_gazetteer(year, kind_source, force), kind_source).items():
            by_state[state].extend(recs)

    total = 0
    out_dir = DATA / "places"
    for state, records in sorted(by_state.items()):
        # a town and a CDP can share a GEOID-distinct footprint with the same name;
        # keep both, disambiguate slugs
        records.sort(key=lambda r: (r["slug"], r["id"]))
        dedupe_slugs(records)
        dump_yaml(records, out_dir / f"{state}.yaml")
        total += len(records)
    print(f"wrote {total} places across {len(by_state)} states/territories -> data/places/")

    meta_path = DATA / "meta.yaml"
    meta = load_yaml(meta_path) if meta_path.exists() else {}
    meta.setdefault("counts", {})["places"] = total
    meta["places_gazetteer_year"] = year
    meta["places_built"] = datetime.date.today().isoformat()
    dump_yaml(meta, meta_path)


if __name__ == "__main__":
    main(sys.argv[1:])
