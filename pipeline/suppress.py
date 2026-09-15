"""Contact-value suppression: values that must never be published.

A source may carry a private individual's number in a field meant for an
organization's public contact line. Honoring a removal request means more than
deleting the record: every module re-emits from its upstream pull on each run,
so an edit to data/ is undone by the next refresh. The denylist in
pipeline/curated/suppressed.yaml is therefore consulted in three places:

- emit.replace_records  — every module write, so a re-pull cannot reintroduce it
- this module's sweep   — one-shot scrub of what is already in data/
- validate              — hard error, so CI refuses to let one through

Entries hold the SHA-256 of the normalized value, never the value itself. This
obscures rather than encrypts (see the header of suppressed.yaml), and is enough
to keep the value out of the repo, its history and its search indexes.

Usage:
    python3 -m pipeline.suppress                 # sweep data/, report + rewrite
    python3 -m pipeline.suppress --check         # report only, exit 1 if any
    python3 -m pipeline.suppress --add VALUE --fields phone --reason TEXT
"""
import hashlib
import re
import sys

import yaml

from .util import DATA, ROOT, load_yaml

LIST = ROOT / "pipeline" / "curated" / "suppressed.yaml"

# fields an entry may name; every one holds a single contact string
CONTACT_FIELDS = ("phone", "fax", "email", "contact_phone")


def normalize(value: str, field: str) -> str:
    """Canonical form a hash is taken over. Phone-ish fields reduce to digits so
    every formatting variant of one number — parenthesised area code, dots,
    dashes, a +1 country prefix — collapses to a single entry; email
    lowercases. Never write a real suppressed value into this file."""
    text = str(value).strip()
    if "mail" in field:
        return text.lower()
    digits = re.sub(r"[^0-9]", "", text)
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    return digits


def digest(value: str, field: str) -> str:
    return hashlib.sha256(normalize(value, field).encode()).hexdigest()


def _load_entries() -> list[dict]:
    if not LIST.exists():
        return []
    return load_yaml(LIST) or []


class Denylist:
    """Hash -> set of fields it applies to ("*" for any)."""

    def __init__(self, entries=None):
        self.by_hash: dict[str, set[str]] = {}
        for e in entries if entries is not None else _load_entries():
            fields = e.get("fields") or ["*"]
            self.by_hash.setdefault(e["sha256"], set()).update(fields)

    def __bool__(self) -> bool:
        return bool(self.by_hash)

    def blocks(self, value, field: str) -> bool:
        if not isinstance(value, str) or not value.strip():
            return False
        fields = self.by_hash.get(digest(value, field))
        return bool(fields) and (field in fields or "*" in fields)

    def scrub(self, rec: dict) -> list[str]:
        """Drop blocked contact fields from `rec` in place. Returns field names
        removed. Absent means absent — the field is deleted, never nulled."""
        hit = []
        if not self.by_hash:
            return hit
        for field in CONTACT_FIELDS:
            if field in rec and self.blocks(rec[field], field):
                del rec[field]
                hit.append(field)
        return hit


_cached: Denylist | None = None


def denylist() -> Denylist:
    """Process-wide singleton — emit calls this per record batch."""
    global _cached
    if _cached is None:
        _cached = Denylist()
    return _cached


def _strip_lines(text: str, field: str, dl: "Denylist") -> tuple[str, int]:
    """Delete whole `field: value` lines whose value is suppressed.

    A surgical text edit, not a YAML round-trip: re-dumping a whole file would
    reflow every record in it and bury a one-line privacy removal in a
    thousand-line diff. The caller re-parses and diffs semantically, so a bad
    edit cannot land.
    """
    out, removed = [], 0
    pattern = re.compile(rf"^\s*{re.escape(field)}:\s*(.+?)\s*$")
    for line in text.splitlines(keepends=True):
        m = pattern.match(line)
        if m:
            value = m.group(1).strip("'\"")
            if dl.blocks(value, field):
                removed += 1
                continue
        out.append(line)
    return "".join(out), removed


def _records(loaded) -> list[dict]:
    body = loaded if isinstance(loaded, list) else [loaded]
    return [r for r in body if isinstance(r, dict)]


def sweep(write: bool = True) -> list[tuple[str, str, str]]:
    """Scrub every record already in data/. Returns (relpath, id, field) hits."""
    dl = denylist()
    hits: list[tuple[str, str, str]] = []
    if not dl:
        return hits
    for kind in ("orgs", "sites", "meetings"):
        base = DATA / kind
        if not base.exists():
            continue
        for path in sorted(base.rglob("*.yaml")):
            before = load_yaml(path)
            found = [(r.get("id", "?"), f)
                     for r in _records(before) for f in CONTACT_FIELDS
                     if f in r and dl.blocks(r[f], f)]
            if not found:
                continue
            rel = str(path.relative_to(DATA))
            hits.extend((rel, rid, field) for rid, field in found)
            if not write:
                continue
            text = path.read_text()
            for field in {f for _, f in found}:
                text, _ = _strip_lines(text, field, dl)
            # semantic check: the edit must remove exactly the offending fields
            after = _records(yaml.safe_load(text))
            expect = []
            for rec in _records(before):
                rec = dict(rec)
                for f in CONTACT_FIELDS:
                    if f in rec and dl.blocks(rec[f], f):
                        del rec[f]
                expect.append(rec)
            if after != expect:
                raise SystemExit(f"suppress: unsafe edit to {rel} — aborted, "
                                 f"file left untouched")
            path.write_text(text)
    return hits


def _add(argv: list[str]) -> int:
    """Append an entry for VALUE without ever writing VALUE to disk."""
    value = argv[argv.index("--add") + 1]
    fields = ["phone"]
    if "--fields" in argv:
        fields = argv[argv.index("--fields") + 1].split(",")
    reason = argv[argv.index("--reason") + 1] if "--reason" in argv else "Removal requested."
    from .emit import today
    sha = digest(value, fields[0])
    entries = _load_entries()
    if any(e["sha256"] == sha for e in entries):
        print(f"already suppressed ({sha[:12]}…)")
        return 0
    block = (f"\n- sha256: {sha}\n"
             f"  fields: [{', '.join(fields)}]\n"
             f"  requested_on: '{today()}'\n"
             f"  reason: >-\n    {reason}\n")
    with LIST.open("a") as f:
        f.write(block)
    print(f"added {sha[:12]}… for {', '.join(fields)} — run the sweep to scrub data/")
    return 0


def main(argv: list[str]) -> int:
    if "--add" in argv:
        return _add(argv)
    check = "--check" in argv
    dl = denylist()
    if not dl:
        print("suppress: denylist empty — nothing to do")
        return 0
    hits = sweep(write=not check)
    verb = "found" if check else "removed"
    for rel, rid, field in hits:
        print(f"{verb} {field} on {rid} ({rel})")
    print(f"suppress: {len(dl.by_hash)} entries, {len(hits)} {verb} "
          f"across {len({h[0] for h in hits})} files")
    if hits and check:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
