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

from .util import DATA, dump_yaml, load_yaml

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


def main(argv):
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
