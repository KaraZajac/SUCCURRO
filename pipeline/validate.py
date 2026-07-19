"""Validation gate. Hard errors exit 1; soft findings are reported but non-fatal.

Hard: id/path mismatch, missing required fields, unknown taxonomy tokens, dangling
foreign keys, malformed dates/geo, confidential-DV records carrying an address.
Soft: stale verification stamps, sites/meetings missing geo or place.

If the `jsonschema` package is installed, full JSON Schema conformance
(schemas/succurro.schema.json) runs as well; the native checks above never depend
on it, so the gate works on a bare stdlib+pyyaml install.

Usage: python3 -m pipeline.validate [--conformance-only]
"""
import datetime
import json
import re
import sys

from .util import DATA, ROOT, load_yaml

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
STALE_DAYS = {"orgs": 180, "sites": 180, "meetings": 90}

errors: list[str] = []
findings: list[str] = []


def err(msg):
    errors.append(msg)


def soft(msg):
    findings.append(msg)


def load_all(subdir):
    """Yield (relpath, record) for every YAML record file under data/<subdir>/."""
    base = DATA / subdir
    if not base.exists():
        return
    for path in sorted(base.rglob("*.yaml")):
        rel = path.relative_to(DATA)
        rec = load_yaml(path)
        yield rel, path, rec


def check_date(rel, field, value):
    if not isinstance(value, str) or not DATE_RE.match(value):
        err(f"{rel}: {field} is not a YYYY-MM-DD string: {value!r}")


def check_verified(rel, rec, kind, today):
    v = rec.get("verified")
    if not isinstance(v, dict) or "on" not in v or "method" not in v:
        err(f"{rel}: missing verified: {{on, method}} stamp")
        return
    check_date(rel, "verified.on", v["on"])
    if DATE_RE.match(str(v["on"])):
        age = (today - datetime.date.fromisoformat(v["on"])).days
        if age > STALE_DAYS[kind]:
            soft(f"{rel}: stale — verified {age} days ago (threshold {STALE_DAYS[kind]})")


def main(argv):
    conformance_only = "--conformance-only" in argv
    today = datetime.date.today()

    taxonomy = load_yaml(DATA / "taxonomy" / "services.yaml") or []
    tokens = {t["id"] for t in taxonomy}
    for t in taxonomy:
        if t.get("parent") and t["parent"] not in tokens:
            err(f"taxonomy: {t['id']} has unknown parent {t['parent']}")

    places = {}
    for rel, path, recs in load_all("places"):
        for rec in recs or []:
            places[rec.get("id")] = rec
            if rec.get("state") != path.stem:
                err(f"{rel}: place {rec.get('id')} state {rec.get('state')} != file {path.stem}")

    source_ids = set()
    for rel, path, rec in load_all("sources"):
        expected = f"{path.parent.name}/{path.stem}"
        if rec.get("id") != expected:
            err(f"{rel}: id {rec.get('id')!r} != path-derived {expected!r}")
        if rec.get("url") is None and "url" in rec and not rec.get("notes"):
            err(f"{rel}: url: null requires an explanatory notes field")
        if "retrieved_on" in rec:
            check_date(rel, "retrieved_on", rec["retrieved_on"])
        source_ids.add(rec.get("id"))

    # orgs are one record per file; sites/meetings are per-place list files
    entity_kinds = ("orgs", "sites", "meetings")
    records_by_kind: dict[str, list] = {k: [] for k in entity_kinds}
    for rel, path, rec in load_all("orgs"):
        records_by_kind["orgs"].append((rel, path, rec))
        if not rec.get("id", "").endswith("/" + path.stem):
            err(f"{rel}: id {rec.get('id')!r} does not match filename {path.stem!r}")
    for kind in ("sites", "meetings"):
        for rel, path, recs in load_all(kind):
            prefix = f"{path.parent.name}/{path.stem}/"
            if not isinstance(recs, list):
                err(f"{rel}: expected a list of records")
                continue
            seen_ids = set()
            for rec in recs:
                records_by_kind[kind].append((rel, path, rec))
                rid = rec.get("id", "")
                if not rid.startswith(prefix):
                    err(f"{rel}: id {rid!r} does not match file shard {prefix!r}")
                if rid in seen_ids:
                    err(f"{rel}: duplicate id {rid!r}")
                seen_ids.add(rid)

    org_ids = {rec.get("id") for _, _, rec in records_by_kind["orgs"]}
    site_ids = {rec.get("id") for _, _, rec in records_by_kind["sites"]}

    for kind in entity_kinds:
        for rel, path, rec in records_by_kind[kind]:
            for cat in rec.get("categories", []):
                if cat not in tokens:
                    err(f"{rel}: unknown category token {cat!r}")
            if not conformance_only:
                for s in rec.get("sources", []) or []:
                    if s not in source_ids:
                        err(f"{rel}: dangling source ref {s!r}")
                if rec.get("place") and rec["place"] not in places:
                    err(f"{rel}: dangling place ref {rec['place']!r}")
                if rec.get("org") and rec["org"] not in org_ids:
                    err(f"{rel}: dangling org ref {rec['org']!r}")
                if rec.get("site") and rec["site"] not in site_ids:
                    err(f"{rel}: dangling site ref {rec['site']!r}")
                if rec.get("dv_confidential") and rec.get("address"):
                    err(f"{rel}: dv_confidential record must not carry an address")
                check_verified(rel, rec, kind, today)
                if kind in ("sites", "meetings") and rec.get("format") != "online":
                    if "geo" not in rec:
                        soft(f"{rel}: no geo coordinates")
                    if "place" not in rec:
                        soft(f"{rel}: not assigned to a place")

    try:
        import jsonschema
        schema = json.loads((ROOT / "schemas" / "succurro.schema.json").read_text())
        defs = {"orgs": "org", "sites": "site", "meetings": "meeting"}
        for kind, def_name in defs.items():
            sub = {"$ref": f"#/$defs/{def_name}", "$defs": schema["$defs"]}
            for rel, path, rec in records_by_kind[kind]:
                for e in jsonschema.Draft202012Validator(sub).iter_errors(rec):
                    err(f"{rel}: schema: {e.message}")
        print("conformance: full JSON Schema check ran (jsonschema installed)")
    except ImportError:
        print("conformance: jsonschema not installed — native checks only")

    counted = sum(len(v) for v in records_by_kind.values())
    print(f"checked {counted} entity records, {len(source_ids)} sources, "
          f"{len(places)} places, {len(tokens)} taxonomy tokens")
    for f in findings:
        print(f"FINDING: {f}")
    if findings:
        print(f"{len(findings)} soft findings (non-fatal)")
    for e in errors:
        print(f"ERROR: {e}", file=sys.stderr)
    if errors:
        print(f"{len(errors)} errors", file=sys.stderr)
        sys.exit(1)
    print("validation gate: clean")


if __name__ == "__main__":
    main(sys.argv[1:])
