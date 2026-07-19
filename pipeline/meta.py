"""Recompute data/meta.yaml counts from disk. Run after any build step.

Usage: python3 -m pipeline.meta
"""
import datetime

from .util import DATA, dump_yaml, load_yaml


def main():
    counts = {}
    counts["places"] = sum(len(load_yaml(p)) for p in (DATA / "places").glob("*.yaml"))
    for kind in ("sites", "meetings"):
        base = DATA / kind
        counts[kind] = sum(len(load_yaml(p) or []) for p in base.rglob("*.yaml")) if base.exists() else 0
    for kind in ("orgs", "sources"):
        base = DATA / kind
        counts[kind] = sum(1 for _ in base.rglob("*.yaml")) if base.exists() else 0

    meta_path = DATA / "meta.yaml"
    meta = load_yaml(meta_path) if meta_path.exists() else {}
    meta["counts"] = counts
    meta["built"] = datetime.date.today().isoformat()
    dump_yaml(meta, meta_path)
    print(" ".join(f"{k}={v}" for k, v in counts.items()))


if __name__ == "__main__":
    main()
