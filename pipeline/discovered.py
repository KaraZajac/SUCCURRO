"""Discovered-org batches -> org records.

Every YAML file in pipeline/curated/discovered/ is one discovery batch:
schema-shaped org records hand-curated by a BMF-verify discovery run (design:
docs/research/discovery-engine-design.md). Each org in a batch was verified
against its own live website on the batch's run date; the per-org `checked:`
field records what was confirmed and stays in the batch file as audit trail —
it is not emitted. The loader adds what discovery runs shouldn't repeat by
hand: a per-batch source record (methodology in its notes), sources/verified/
provisional stamps, place FK resolution, and dedup against orgs already on
disk from other sources (normalized name+state; skip, never overwrite).

Batch file shape (loader-consumed keys beyond the org schema):
  batch: 2026-07-pilot        # -> source id discovered/<batch>
  run_on: "2026-07-20"        # verification/retrieval date for the whole batch
  title: ...                  # source record title
  notes: ...                  # source record methodology notes
  orgs:
    - name: ...
      state: az               # HQ state -> id prefix
      city: Phoenix           # place-resolution hint (DV orgs carry no address)
      categories: [seniors]
      address: {street: ..., city: Phoenix, state: az, zip: "85014"}
      checked: what the run confirmed, on which pages   # audit trail, dropped
      ...any other org-schema field (website, phone, external_ids, aliases...)

DV policy: domestic-violence orgs are curated without address (city hint
only); they get a service_area instead so coverage still counts.

Usage: python3 -m pipeline.discovered
"""
import sys
from pathlib import Path

from .emit import Places, norm, replace_records, write_source
from .util import Flow, load_yaml

BATCH_DIR = Path(__file__).parent / "curated" / "discovered"

# every batch cites a discovered/<batch> source; the trailing-slash prefix
# makes this module own all of them at once (see emit._cites)
OWNER = "discovered/"

FIELD_ORDER = ("categories", "description", "aliases", "address", "place",
               "website", "phone", "email", "service_area", "languages",
               "external_ids", "provisional", "sources", "verified")


def existing_names() -> set[tuple[str, str]]:
    """(state, normalized name/alias) for every org not owned by a batch."""
    from .util import DATA
    seen = set()
    base = DATA / "orgs"
    for path in sorted(base.rglob("*.yaml")) if base.exists() else []:
        rec = load_yaml(path)
        if any(s.startswith(OWNER) for s in rec.get("sources", [])):
            continue
        state = rec["id"].split("/")[0]
        seen.add((state, norm(rec["name"])))
        for alias in rec.get("aliases", []):
            seen.add((state, norm(alias)))
    return seen


def main(argv):
    places = Places()
    seen = existing_names()
    records, skipped = [], 0
    for path in sorted(BATCH_DIR.glob("*.yaml")):
        batch = load_yaml(path)
        source_id = write_source(
            "discovered", batch["batch"],
            kind="org-website", publisher="SUCCURRO (BMF discovery)",
            title=batch["title"], url=None, notes=batch["notes"],
            tier="primary", retrieved_on=batch["run_on"],
        )
        for org in batch["orgs"]:
            org = dict(org)
            state = org.pop("state")
            name = org["name"]
            if (state, norm(name)) in seen:
                skipped += 1
                print(f"skip (already present from another source): {state}/{name}")
                continue
            org.pop("name")
            org.pop("checked", None)  # audit trail lives in the batch file
            city = org.pop("city", None) or (org.get("address") or {}).get("city")
            geoid, place_slug = places.resolve(state, city or "")
            if geoid:
                org["place"] = geoid
            if "address" in org:
                org["address"] = Flow(org["address"])
            elif city and "service_area" not in org:
                # no address published (e.g. DV policy) — record where it serves
                org["service_area"] = Flow(kind="place", name=city, state=state)
            if "service_area" in org and not isinstance(org["service_area"], Flow):
                org["service_area"] = Flow(org["service_area"])
            if "external_ids" in org:
                org["external_ids"] = Flow(org["external_ids"])
            org["provisional"] = True
            org["sources"] = [source_id]
            org["verified"] = Flow(on=org.pop("verified_on", batch["run_on"]),
                                   method="scrape")
            rec = {"_state": state, "_place_slug": place_slug, "_name": name}
            rec.update((k, org.pop(k)) for k in FIELD_ORDER if k in org)
            rec.update(org)  # anything else the batch curated
            records.append(rec)
    print(f"discovered: {len(records)} orgs from batches, {skipped} skipped as dupes")
    replace_records("orgs", OWNER, records)


if __name__ == "__main__":
    main(sys.argv[1:])
