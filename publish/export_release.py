#!/usr/bin/env python3
"""export_release.py — build the citable release bundle from the canonical YAML.

Deterministic and engine-independent (family convention): what a replicator
downloads is derived from data/ by this one inspectable script. Same inputs
always produce byte-identical outputs — ids are content-derived (UUIDv5 over a
fixed namespace), records are key-sorted, files are written in sorted order.

    python3 publish/export_release.py [--tag v1.0]

Writes release/succurro-<tag>/:
    orgs.jsonl sites.jsonl meetings.jsonl sources.jsonl places.jsonl
    taxonomy.jsonl                     the canonical records, one JSON per line
    hsds/*.csv                         Open Referral HSDS 3.0 tabular export
    succurro.schema.json               the JSON Schema (copied)
    stats.json                         counts that feed the datasheet + paper
    DATASHEET.md                       copied from publish/
    SHA256SUMS                         integrity manifest
    README.md                          what this bundle is, license, citation
"""
import argparse
import csv
import hashlib
import json
import shutil
import subprocess
import sys
import uuid
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from pipeline.util import DATA, ROOT, load_yaml  # noqa: E402

# fixed namespace so HSDS UUIDs are stable across releases
NS = uuid.UUID("6ba7b812-9dad-11d1-80b4-00c04fd430c8")
uid = lambda kind, key: str(uuid.uuid5(NS, f"succurro:{kind}:{key}"))

DAYS = {"mon": "MO", "tue": "TU", "wed": "WE", "thu": "TH",
        "fri": "FR", "sat": "SA", "sun": "SU"}


def iter_records(kind):
    """Yield every record of a per-place-list kind (sites/meetings)."""
    base = DATA / kind
    if not base.exists():
        return
    for path in sorted(base.rglob("*.yaml")):
        for rec in load_yaml(path) or []:
            yield rec


def iter_orgs():
    base = DATA / "orgs"
    for path in sorted(base.rglob("*.yaml")):
        yield load_yaml(path)


def iter_sources():
    for path in sorted((DATA / "sources").rglob("*.yaml")):
        yield load_yaml(path)


def iter_places():
    for path in sorted((DATA / "places").glob("*.yaml")):
        for rec in load_yaml(path) or []:
            yield rec


def write_jsonl(path, records):
    n = 0
    with path.open("w", encoding="utf-8") as f:
        for rec in records:
            f.write(json.dumps(rec, ensure_ascii=False, sort_keys=True,
                               default=str) + "\n")
            n += 1
    return n


class HSDS:
    """Open Referral HSDS 3.0 export.

    Mapping (documented in the bundle README — HSDS models providers, not
    directories, so the shapes differ from ours):
      org record            -> organization (+ location when it has an address)
      site record           -> service + location + service_at_location
      meeting record        -> service + location (venue) + schedule
      site/meeting w/o org  -> a synthetic organization for that provider,
                               because HSDS requires service.organization_id
      taxonomy token        -> taxonomy_term; categories -> service_attribute
    """

    TABLES = {
        "organization": ["id", "name", "alternate_name", "description", "email",
                         "website", "parent_organization_id"],
        "service": ["id", "organization_id", "name", "description", "status",
                    "url", "email", "fees_description", "eligibility_description"],
        "location": ["id", "location_type", "organization_id", "name",
                     "latitude", "longitude", "external_identifier",
                     "external_identifier_type"],
        "address": ["id", "location_id", "address_1", "address_2", "city",
                    "state_province", "postal_code", "country", "address_type"],
        "phone": ["id", "location_id", "service_id", "organization_id", "number"],
        "schedule": ["id", "service_id", "service_at_location_id", "valid_from",
                     "valid_to", "freq", "wkst", "opens_at", "closes_at",
                     "description"],
        "service_at_location": ["id", "service_id", "location_id"],
        "taxonomy_term": ["id", "code", "name", "parent_id", "taxonomy"],
        "service_attribute": ["id", "service_id", "taxonomy_term_id", "link_id",
                              "link_type"],
        "metadata": ["id", "resource_id", "resource_type", "last_action_date",
                     "last_action_type", "field_name", "previous_value",
                     "replacement_value", "updated_by"],
    }

    def __init__(self, outdir):
        self.dir = outdir / "hsds"
        self.dir.mkdir(parents=True, exist_ok=True)
        self.files, self.writers, self.counts = {}, {}, {}
        for table, cols in self.TABLES.items():
            f = (self.dir / f"{table}.csv").open("w", newline="", encoding="utf-8")
            w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
            w.writeheader()
            self.files[table], self.writers[table], self.counts[table] = f, w, 0

    def row(self, table, **fields):
        self.writers[table].writerow({k: v for k, v in fields.items() if v not in (None, "")})
        self.counts[table] += 1

    def close(self):
        for f in self.files.values():
            f.close()

    # -- emitters ---------------------------------------------------------
    def organization(self, rec):
        self.row("organization", id=uid("org", rec["id"]), name=rec["name"],
                 alternate_name="; ".join(rec.get("aliases") or []) or None,
                 description=rec.get("description"), email=rec.get("email"),
                 website=rec.get("website"),
                 parent_organization_id=(uid("org", rec["parent_org"])
                                         if rec.get("parent_org") else None))
        if rec.get("phone"):
            self.row("phone", id=uid("phone", rec["id"]),
                     organization_id=uid("org", rec["id"]), number=rec["phone"])
        if rec.get("address") or rec.get("geo"):
            self._location(rec, uid("org", rec["id"]), "org-loc")

    def _location(self, rec, org_id, kind, name=None):
        loc_id = uid(kind, rec["id"])
        geo = rec.get("geo") or {}
        addr = rec.get("address") or rec.get("venue") or {}
        self.row("location", id=loc_id,
                 location_type="virtual" if rec.get("format") == "online" else "physical",
                 organization_id=org_id,
                 name=name or rec.get("venue_name") or rec["name"],
                 latitude=geo.get("lat"), longitude=geo.get("lng"),
                 external_identifier=rec.get("place"),
                 external_identifier_type="us-census-geoid" if rec.get("place") else None)
        if addr.get("city"):
            self.row("address", id=uid("addr", rec["id"]), location_id=loc_id,
                     address_1=addr.get("street"), address_2=addr.get("street2"),
                     city=addr.get("city"),
                     state_province=(addr.get("state") or "").upper(),
                     postal_code=addr.get("zip"), country="US",
                     address_type="physical")
        return loc_id

    def _attributes(self, rec, service_id):
        for token in rec.get("categories") or []:
            self.row("service_attribute",
                     id=uid("attr", f"{rec['id']}:{token}"), service_id=service_id,
                     taxonomy_term_id=uid("term", token), link_id=service_id,
                     link_type="service")

    def service_like(self, rec, kind):
        """A site or meeting -> service (+ location, schedule, attributes)."""
        org_ref = rec.get("org")
        org_id = uid("org", org_ref) if org_ref else uid("org", f"self:{rec['id']}")
        if not org_ref:  # HSDS requires an organization for every service
            self.row("organization", id=org_id, name=rec["name"],
                     description=rec.get("description"), website=rec.get("website"))
        svc_id = uid("svc", rec["id"])
        self.row("service", id=svc_id, organization_id=org_id, name=rec["name"],
                 description=rec.get("description"), status="active",
                 url=rec.get("website") or rec.get("url"), email=rec.get("email"),
                 fees_description=rec.get("cost"),
                 eligibility_description=rec.get("eligibility"))
        self._attributes(rec, svc_id)
        if rec.get("phone"):
            self.row("phone", id=uid("phone", rec["id"]), service_id=svc_id,
                     number=rec["phone"])
        loc_id = self._location(rec, org_id, f"{kind}-loc")
        sal_id = uid("sal", rec["id"])
        self.row("service_at_location", id=sal_id, service_id=svc_id, location_id=loc_id)
        for i, entry in enumerate(rec.get("schedule") or []):
            self.row("schedule", id=uid("sched", f"{rec['id']}:{i}"),
                     service_id=svc_id, service_at_location_id=sal_id,
                     freq="WEEKLY", wkst=DAYS.get(entry.get("day")),
                     opens_at=entry.get("time"), description=entry.get("note"))
        for i, entry in enumerate(rec.get("hours") or []):
            for day in entry.get("days") or []:
                self.row("schedule", id=uid("sched", f"{rec['id']}:h{i}:{day}"),
                         service_id=svc_id, service_at_location_id=sal_id,
                         freq="WEEKLY", wkst=DAYS.get(day),
                         opens_at=entry.get("open"), closes_at=entry.get("close"),
                         description=entry.get("note"))

    def taxonomy(self, terms):
        for t in terms:
            self.row("taxonomy_term", id=uid("term", t["id"]), code=t["id"],
                     name=t["label"],
                     parent_id=uid("term", t["parent"]) if t.get("parent") else None,
                     taxonomy="SUCCURRO service taxonomy")


BUNDLE_README = """# SUCCURRO release bundle — {tag}

Curated, source-anchored directory of help and support services across the
United States, resolved to the city and town level.

Built {built} from the canonical YAML in the SUCCURRO repository by
`publish/export_release.py`. Deterministic: the same repository state
reproduces this bundle byte for byte.

## Contents

| File | What |
|---|---|
| `orgs.jsonl` | {orgs:,} organizations |
| `sites.jsonl` | {sites:,} service locations |
| `meetings.jsonl` | {meetings:,} recurring meetings and support groups |
| `sources.jsonl` | {sources:,} first-class source records (provenance) |
| `places.jsonl` | {places:,} US places (Census-derived geo backbone) |
| `taxonomy.jsonl` | {terms} service-category taxonomy terms |
| `hsds/*.csv` | the same data as Open Referral **HSDS 3.0** tables |
| `succurro.schema.json` | JSON Schema for the canonical records |
| `stats.json` | counts and coverage measures |
| `DATASHEET.md` | datasheet (Gebru et al. framework) |
| `SHA256SUMS` | integrity manifest |

## The record model in one paragraph

An **organization** is an entity that provides help (a NAMI affiliate, a food
bank, a county veteran service office). A **site** is a physical place where
help is delivered. A **meeting** is a recurring gathering (an AA meeting, a
grief support group). Every record cites at least one **source** record and
carries a `verified` stamp with the date it was last checked against that
source. Absent fields are omitted rather than nulled; enumerated fields use
kebab-case tokens defined in `taxonomy.jsonl`.

## HSDS export

`hsds/` re-expresses the dataset in Open Referral's Human Service Data
Specification 3.0 so it can be loaded by HSDS-compatible tooling. HSDS models
individual providers rather than a directory-of-directories, so the mapping is
lossy in one direction: services delivered at a site with no distinct parent
organization get a synthetic organization (HSDS requires `service.organization_id`),
and SUCCURRO's provenance fields (`sources`, `verified`) have no HSDS home —
they live only in the JSONL. Ids are deterministic UUIDv5 values derived from
SUCCURRO ids, so they are stable across releases.

## Rights

Dataset: **CC BY-NC 4.0**. Code: MIT. Rights are layered per source — federal
datasets are public domain, community feeds and directories are re-expressed
as facts with per-record citation. See `DATA-RIGHTS.md` in the repository for
the full table, including the sources deliberately **not** collected because
their terms prohibit it.

## Freshness and safety

Service directories go stale in ways that matter. Every record carries
`verified: {{on, method}}`. Safety-critical categories (crisis lines, domestic
violence services, shelters) are suppressed from the public site rather than
shown stale. Confidential domestic-violence shelter addresses are never
published — only hotline and intake contacts. Meeting records carry venue and
schedule facts only, respecting the anonymity traditions of the fellowships
they describe.

Corrections and takedown requests are honored without argument:
https://github.com/KaraZajac/SUCCURRO

## Citation

See `CITATION.cff` in the repository.
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", default=None, help="release tag (default: git describe)")
    args = ap.parse_args()
    tag = args.tag
    if not tag:
        try:
            tag = subprocess.check_output(["git", "describe", "--tags", "--always"],
                                          cwd=ROOT, text=True).strip()
        except Exception:
            tag = "untagged"

    outdir = ROOT / "release" / f"succurro-{tag}"
    outdir.mkdir(parents=True, exist_ok=True)
    print(f"building {outdir.relative_to(ROOT)}")

    taxonomy = load_yaml(DATA / "taxonomy" / "services.yaml")
    hsds = HSDS(outdir)
    hsds.taxonomy(taxonomy)

    counts = {}
    counts["taxonomy"] = write_jsonl(outdir / "taxonomy.jsonl", taxonomy)
    counts["places"] = write_jsonl(outdir / "places.jsonl", iter_places())
    counts["sources"] = write_jsonl(outdir / "sources.jsonl", iter_sources())

    def tee(records, kind):
        for rec in records:
            if kind == "orgs":
                hsds.organization(rec)
            else:
                hsds.service_like(rec, kind)
            yield rec

    counts["orgs"] = write_jsonl(outdir / "orgs.jsonl", tee(iter_orgs(), "orgs"))
    counts["sites"] = write_jsonl(outdir / "sites.jsonl",
                                  tee(iter_records("sites"), "site"))
    counts["meetings"] = write_jsonl(outdir / "meetings.jsonl",
                                     tee(iter_records("meetings"), "meeting"))
    hsds.close()

    # ---- stats.json -----------------------------------------------------
    meta = load_yaml(DATA / "meta.yaml")
    by_source, by_category, by_state, coverage = {}, {}, {}, {}
    stamped = geo = placed = 0
    total_records = 0
    for kind in ("sites", "meetings"):
        for rec in iter_records(kind):
            total_records += 1
            fam = (rec.get("sources") or ["?"])[0].split("/")[0]
            by_source[fam] = by_source.get(fam, 0) + 1
            st = rec["id"].split("/")[0]
            by_state[st] = by_state.get(st, 0) + 1
            for cat in rec.get("categories") or []:
                by_category[cat] = by_category.get(cat, 0) + 1
            if rec.get("verified", {}).get("on"):
                stamped += 1
            if rec.get("geo"):
                geo += 1
            if rec.get("place"):
                placed += 1
    for rec in iter_orgs():
        fam = (rec.get("sources") or ["?"])[0].split("/")[0]
        by_source[fam] = by_source.get(fam, 0) + 1
        for cat in rec.get("categories") or []:
            by_category[cat] = by_category.get(cat, 0) + 1
    coverage = {
        "records_with_verified_stamp_pct": round(100 * stamped / max(total_records, 1), 1),
        "site_meeting_records_with_geo_pct": round(100 * geo / max(total_records, 1), 1),
        "site_meeting_records_with_place_fk_pct": round(100 * placed / max(total_records, 1), 1),
    }
    stats = {
        "tag": tag,
        "built": date.today().isoformat(),
        "counts": counts,
        "meta_counts": meta.get("counts", {}),
        "hsds_rows": hsds.counts,
        "coverage": coverage,
        "records_by_source_family": dict(sorted(by_source.items(), key=lambda kv: -kv[1])),
        "records_by_category": dict(sorted(by_category.items(), key=lambda kv: -kv[1])),
        "records_by_state": dict(sorted(by_state.items())),
    }
    (outdir / "stats.json").write_text(json.dumps(stats, indent=2, sort_keys=False) + "\n")

    # ---- copies + bundle README ----------------------------------------
    shutil.copy(ROOT / "schemas" / "succurro.schema.json", outdir / "succurro.schema.json")
    datasheet = ROOT / "publish" / "DATASHEET.md"
    if datasheet.exists():
        shutil.copy(datasheet, outdir / "DATASHEET.md")
    (outdir / "README.md").write_text(BUNDLE_README.format(
        tag=tag, built=date.today().isoformat(), terms=counts["taxonomy"],
        orgs=counts["orgs"], sites=counts["sites"], meetings=counts["meetings"],
        sources=counts["sources"], places=counts["places"]))

    # ---- SHA256SUMS -----------------------------------------------------
    lines = []
    for path in sorted(outdir.rglob("*")):
        if path.is_file() and path.name != "SHA256SUMS":
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            lines.append(f"{digest}  {path.relative_to(outdir)}")
    (outdir / "SHA256SUMS").write_text("\n".join(lines) + "\n")

    size = sum(p.stat().st_size for p in outdir.rglob("*") if p.is_file())
    print(json.dumps(counts, indent=2))
    print(f"hsds rows: {json.dumps(hsds.counts)}")
    print(f"bundle: {len(lines)} files, {size / 1e6:.1f} MB -> {outdir}")


if __name__ == "__main__":
    main()
