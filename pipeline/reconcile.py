"""Cross-source reconciliation. Runs after all source modules (make build).

Co-located records offering different services (a school that is both a Head
Start center and a summer meal site) are legitimate and left alone. True
duplicates are removed by layered precedence — currently one rule:

- A SAMHSA FindTreatment record sharing a normalized (street, city, state)
  with a VA Facilities record is the same VA-run facility seen through a
  weaker lens (no hours/services); the VA record wins and the SAMHSA copy is
  dropped. Deterministic: re-running modules re-adds copies, re-running
  reconcile re-drops them.

Usage: python3 -m pipeline.reconcile
"""
import re
import sys
from pathlib import Path

from .emit import _reflow
from .util import DATA, Flow, dump_yaml, load_yaml

_norm = re.compile(r"[^a-z0-9]+")


def norm(text):
    return _norm.sub("", (text or "").lower())


def addr_key(rec):
    a = rec.get("address") or {}
    if not a.get("street") or not a.get("city"):
        return None
    return (norm(a["street"]), norm(a["city"]), a.get("state"))


def source_family(rec):
    src = (rec.get("sources") or [""])[0]
    return src.split("/")[0]


MERGE_FILL = ("address", "geo", "phone", "email", "website", "description",
              "service_area", "parent_org")


def merge_org_duplicates():
    """Same-name, same-state orgs arriving via different source networks are
    the same organization wearing multiple hats (a food bank that is also a
    diaper-bank member; a legal-aid org that is also a DV program). Merge:
    the fuller record wins as base, categories/sources/external_ids union,
    missing scalars fill from the others, duplicates are deleted.
    Deterministic, so module re-runs followed by reconcile converge."""
    groups = {}
    base_dir = DATA / "orgs"
    for path in sorted(base_dir.rglob("*.yaml")):
        rec = load_yaml(path)
        key = (norm(rec.get("name", "")), rec["id"].split("/")[0])
        groups.setdefault(key, []).append((path, rec))

    merged = 0
    for key, entries in groups.items():
        families = {r["sources"][0].split("/")[0] for _, r in entries}
        if len(entries) < 2 or len(families) < 2:
            continue
        entries.sort(key=lambda pr: (-len(pr[1]), pr[1]["id"]))
        base_path, base = entries[0]
        for path, other in entries[1:]:
            for cat in other.get("categories", []):
                if cat not in base["categories"]:
                    base["categories"].append(cat)
            for src in other.get("sources", []):
                if src not in base["sources"]:
                    base["sources"].append(src)
            if other.get("external_ids"):
                ids = dict(other["external_ids"])
                ids.update(base.get("external_ids") or {})
                base["external_ids"] = Flow(ids)
            for field in MERGE_FILL:
                if field not in base and field in other:
                    base[field] = other[field]
            if (other.get("verified", {}).get("on", "") >
                    base.get("verified", {}).get("on", "")):
                base["verified"] = other["verified"]
            path.unlink()
            merged += 1
        dump_yaml(_reflow(base), base_path)
    print(f"reconcile: merged {merged} cross-source duplicate orgs")


def main(argv):
    merge_org_duplicates()
    va_addrs = set()
    files = sorted((DATA / "sites").rglob("*.yaml"))
    for path in files:
        for rec in load_yaml(path) or []:
            if source_family(rec) == "va":
                key = addr_key(rec)
                if key:
                    va_addrs.add(key)

    dropped = 0
    for path in files:
        records = load_yaml(path) or []
        kept = []
        for rec in records:
            if (source_family(rec) == "samhsa" and addr_key(rec) in va_addrs):
                dropped += 1
                continue
            kept.append(rec)
        if len(kept) != len(records):
            if kept:
                dump_yaml(kept, path)
            else:
                path.unlink()
    print(f"reconcile: dropped {dropped} SAMHSA duplicates of VA facilities")


if __name__ == "__main__":
    main(sys.argv[1:])
