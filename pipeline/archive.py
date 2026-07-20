"""Wayback-archive source URLs (AUSPEX pattern, link-rot defense).

For every source record lacking archive_url: check the Wayback availability
API for an existing snapshot; with --save, request Save-Page-Now for URLs
that have none (throttled hard — SPN asks ~15s between requests). Updates
the source YAML in place.

Usage: python3 -m pipeline.archive [--save]
"""
import json
import sys
import time
import urllib.parse

from .util import DATA, UA, dump_yaml, get, load_yaml

AVAIL = "https://archive.org/wayback/available?url={u}"
SPN = "https://web.archive.org/save/{u}"


def main(argv):
    save = "--save" in argv
    updated = missing = 0
    for path in sorted((DATA / "sources").rglob("*.yaml")):
        rec = load_yaml(path)
        url = rec.get("url")
        if not url or rec.get("archive_url"):
            continue
        quoted = urllib.parse.quote(url, safe="")
        try:
            data = json.loads(get(AVAIL.format(u=quoted), timeout=60))
        except SystemExit as e:
            print(f"WARNING: availability check failed for {rec['id']}: {e}")
            continue
        snap = (data.get("archived_snapshots") or {}).get("closest") or {}
        if snap.get("available") and snap.get("url"):
            rec["archive_url"] = snap["url"].replace("http://", "https://", 1)
            dump_yaml(rec, path)
            updated += 1
            continue
        missing += 1
        if save:
            print(f"saving {url} ...")
            try:
                get(SPN.format(u=url), timeout=180)
            except SystemExit as e:
                print(f"WARNING: save-page-now failed for {rec['id']}: {e}")
            time.sleep(15)
    print(f"archive: {updated} archive_url added, {missing} with no snapshot"
          + ("" if save else " (re-run with --save to request snapshots)"))


if __name__ == "__main__":
    main(sys.argv[1:])
