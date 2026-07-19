"""Record emission: place resolution and source-owned record replacement.

Storage layout:
- sites/meetings: per-place LIST files — data/<kind>/<state>/<place-slug>.yaml
  holds a list of records; a record's id is <state>/<place-slug>/<slug>.
- orgs: one file per record — data/orgs/<state>/<slug>.yaml.

Each pipeline module owns exactly the records that cite its source id. Re-running
a module drops its old records and writes the new pull (newest wins), leaving
other sources' records untouched. Slugs are uniquified deterministically against
everything already on disk.
"""
import datetime
import re
from collections import defaultdict
from pathlib import Path

from .util import DATA, dump_yaml, load_yaml, slugify

_norm = re.compile(r"[^a-z0-9]+")


def norm(text: str) -> str:
    return _norm.sub("", text.lower())


class Places:
    """City-name and coordinate -> place lookup built from data/places/."""

    def __init__(self):
        self.by_state: dict[str, dict[str, tuple[str, str]]] = {}
        self._grid: dict[tuple[int, int], list] = {}
        for path in sorted((DATA / "places").glob("*.yaml")):
            index = {}
            for rec in load_yaml(path):
                index.setdefault(norm(rec["name"]), (rec["id"], rec["slug"]))
                lat, lng = rec["geo"]["lat"], rec["geo"]["lng"]
                cell = (int(lat * 2), int(lng * 2))  # ~half-degree grid
                self._grid.setdefault(cell, []).append(
                    (lat, lng, path.stem, rec["id"], rec["slug"]))
            self.by_state[path.stem] = index

    def resolve(self, state: str, city: str) -> tuple[str | None, str]:
        """Return (geoid or None, place path slug). Unmatched cities still get a
        stable slug so records shard sensibly; the validator soft-finds them."""
        if not city:
            return None, "unknown"
        state = state.lower()
        index = self.by_state.get(state, {})
        key = norm(city)
        if key in index:
            return index[key]
        # common alias: Saint/St., Mount/Mt., Fort/Ft.
        for a, b in (("saint", "st"), ("mount", "mt"), ("fort", "ft")):
            if key.startswith(a):
                alt = b + key[len(a):]
                if alt in index:
                    return index[alt]
            if key.startswith(b):
                alt = a + key[len(b):]
                if alt in index:
                    return index[alt]
        return None, slugify(city) or "unknown"

    def nearest(self, lat: float, lng: float) -> tuple[str, str, str] | None:
        """Nearest registry place to a coordinate: (state, geoid, slug), or None
        if nothing within ~1.5 degrees. Approximate planar distance — fine for
        assigning a point to its town."""
        cy, cx = int(lat * 2), int(lng * 2)
        best, best_d2 = None, 9.0
        for dy in (-2, -1, 0, 1, 2):
            for dx in (-2, -1, 0, 1, 2):
                for plat, plng, state, geoid, slug in self._grid.get((cy + dy, cx + dx), []):
                    d2 = (plat - lat) ** 2 + ((plng - lng) * 0.78) ** 2
                    if d2 < best_d2:
                        best, best_d2 = (state, geoid, slug), d2
        return best


def today() -> str:
    return datetime.date.today().isoformat()


def write_source(pub_dir: str, slug: str, **fields) -> str:
    """Write/update a first-class source record under data/sources/<pub_dir>/;
    `fields` must include the human-readable `publisher`. Returns the source id."""
    sid = f"{pub_dir}/{slug}"
    rec = {"id": sid, **fields}
    rec.setdefault("retrieved_on", today())
    dump_yaml(rec, DATA / "sources" / pub_dir / f"{slug}.yaml")
    return sid


def _cites(rec: dict, source_id: str) -> bool:
    """True if the record cites source_id. A trailing-slash source_id is a
    prefix match ("aa/" owns every record citing any aa/<feed> source) so a
    multi-feed module owns its whole family, including feeds since removed
    from its registry."""
    sources = rec.get("sources") or []
    if source_id.endswith("/"):
        return any(s.startswith(source_id) for s in sources)
    return source_id in sources


def replace_records(kind: str, source_id: str, records: list[dict]):
    """Replace all records of `kind` owned by `source_id` with `records`.

    Incoming records carry `_state`, `_place_slug`, `_name` (and everything else
    final). Ids are assigned here, uniquified against records kept from other
    sources. Records already carrying `id` keep it.
    """
    base = DATA / kind
    kept: dict[Path, list[dict]] = defaultdict(list)
    taken: set[str] = set()

    if kind == "orgs":
        for path in sorted(base.rglob("*.yaml")) if base.exists() else []:
            rec = load_yaml(path)
            if _cites(rec, source_id):
                path.unlink()
            else:
                taken.add(rec["id"])
    else:
        for path in sorted(base.rglob("*.yaml")) if base.exists() else []:
            remaining = [r for r in load_yaml(path) or [] if not _cites(r, source_id)]
            if remaining:
                kept[path] = remaining
                taken.update(r["id"] for r in remaining)
            else:
                path.unlink()  # file held only this source's records (or was empty)

    grouped: dict[Path, list[dict]] = defaultdict(list)
    for rec in sorted(records, key=lambda r: (r["_state"], r["_place_slug"], r["_name"])):
        state, place_slug = rec.pop("_state"), rec.pop("_place_slug")
        name = rec.pop("_name")
        stem = slugify(name) or "unnamed"
        prefix = f"{state}/{place_slug}" if kind != "orgs" else state
        rid = rec.get("id") or f"{prefix}/{stem}"
        n = 2
        while rid in taken:
            rid = f"{prefix}/{stem}-{n}"
            n += 1
        taken.add(rid)
        rec = {"id": rid, "name": name, **rec}
        if kind == "orgs":
            grouped[base / state / f"{rid.split('/')[-1]}.yaml"].append(rec)
        else:
            grouped[base / state / f"{place_slug}.yaml"].append(rec)

    if kind == "orgs":
        for path, recs in grouped.items():
            dump_yaml(recs[0], path)
    else:
        merged: dict[Path, list[dict]] = defaultdict(list, kept)
        for path, recs in grouped.items():
            merged[path].extend(recs)
        for path, recs in merged.items():
            dump_yaml(sorted(recs, key=lambda r: r["id"]), path)

    print(f"{kind}: wrote {len(records)} records for {source_id}")
