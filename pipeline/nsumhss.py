"""SAMHSA N-SUMHSS national directories -> LGBTQ+-affirming treatment flag.

findtreatment.gov's locator export carries 23 special-population codes —
veterans, HIV/AIDS, trauma, PTSD, seniors — but none for LGBTQ+ clients, and
the locator API rejects the code outright. SAMHSA still collects it: the annual
N-SUMHSS survey asks whether a facility runs "a program or group specifically
tailored for LGBT clients" (category SG, code GL), and publishes the answers
facility-by-facility in the two National Directories as XLSX.

This is an enrichment post-pass, not a source module. It owns exactly one
category token on records another module emits, so it must run after
findtreatment — and it re-applies on every build, because replace_records
rewrites those records from the locator pull each time.

Matching is deliberately exact: normalized name or street, plus city and state.
Fuzzy matching would raise the hit rate and would also, sooner or later, label
a facility as LGBTQ+-affirming when it is not — a worse failure here than a
missing flag, since someone acts on it by walking through the door. About 69%
of flagged directory rows match a locator record; the rest are mostly drift
between the 2024 survey and the current locator. The flag is a lower bound.

Usage: python3 -m pipeline.nsumhss [--force]
"""
import hashlib
import re
import sys
import xml.etree.ElementTree as ET
import zipfile
from collections import defaultdict

from .emit import _reflow, today, write_source
from .util import DATA, SOURCES, dump_yaml, fetch, load_yaml

YEAR = 2024
BASE = "https://www.samhsa.gov/data/sites/default/files/reports"
DIRECTORIES = {
    "su": (f"{BASE}/rpt53015/National%20Directory%20SU%20{YEAR}_Final.xlsx",
           f"National Directory of Drug and Alcohol Use Treatment Facilities ({YEAR})"),
    "mh": (f"{BASE}/rpt53016/National%20Directory%20MH%20{YEAR}_Final.xlsx",
           f"National Directory of Mental Health Treatment Facilities ({YEAR})"),
}
TOKEN = "lgbtq-affirming"
GL_RE = re.compile(r"\bGL\b")  # unique across all 224 codes in the legend

NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
_norm = re.compile(r"[^a-z0-9]+")
SUFFIX = re.compile(r"\b(inc|llc|llp|pc|pa|corp|corporation|company|co|ltd|the)\b")
ABBR = {"street": "st", "avenue": "ave", "road": "rd", "drive": "dr",
        "boulevard": "blvd", "suite": "ste", "north": "n", "south": "s",
        "east": "e", "west": "w", "highway": "hwy", "place": "pl",
        "court": "ct", "lane": "ln", "parkway": "pkwy"}


def norm(text):
    return _norm.sub("", (text or "").lower())


def nname(text):
    return _norm.sub("", SUFFIX.sub("", (text or "").lower()))


def nstreet(text):
    text = (text or "").lower()
    for long, short in ABBR.items():
        text = re.sub(rf"\b{long}\b", short, text)
    return _norm.sub("", text)


def sheet_rows(path, sheet="xl/worksheets/sheet1.xml"):
    """Yield each row of an xlsx sheet as a dict. stdlib only: xlsx is a zip of
    XML, and PyYAML is the project's one dependency."""
    zf = zipfile.ZipFile(path)
    strings = ["".join(t.text or "" for t in si.iter(NS + "t"))
               for si in ET.fromstring(zf.read("xl/sharedStrings.xml")).iter(NS + "si")]
    header = None
    for row in ET.fromstring(zf.read(sheet)).iter(NS + "row"):
        cells = []
        for cell in row.iter(NS + "c"):
            v = cell.find(NS + "v")
            value = "" if v is None else (v.text or "")
            if cell.get("t") == "s" and value:
                value = strings[int(value)]
            cells.append(value)
        if header is None:
            header = cells
            continue
        yield dict(zip(header, cells + [""] * (len(header) - len(cells))))


def flagged_rows(force):
    """Every directory row whose service codes include GL, plus file digests."""
    rows, digests = [], {}
    for key, (url, title) in DIRECTORIES.items():
        cache = SOURCES / "samhsa" / "nsumhss" / f"{key}-{YEAR}.xlsx"
        path = fetch(url, cache, force=force)
        digests[key] = hashlib.sha256(path.read_bytes()).hexdigest()
        found = [r for r in sheet_rows(path)
                 if GL_RE.search(r.get("service_code_info", ""))]
        if len(found) < 500:
            raise SystemExit(
                f"nsumhss: only {len(found)} GL rows in the {key} directory — "
                f"the layout or the code legend changed; refusing to run.")
        print(f"{key}: {len(found)} facilities with a tailored LGBTQ+ program")
        rows.extend(found)
    return rows, digests


def main(argv):
    force = "--force" in argv
    rows, digests = flagged_rows(force)

    source_id = write_source(
        "samhsa", "nsumhss-directory",
        kind="dataset", publisher="SAMHSA (CBHSQ)",
        title=f"N-SUMHSS National Directories ({YEAR})",
        url=("https://www.samhsa.gov/data/data-we-collect/"
             "n-sumhss-national-substance-use-and-mental-health-services-survey/"
             f"national-directories/{YEAR}"),
        tier="primary", retrieved_on=today(),
        sha256_su=digests["su"], sha256_mh=digests["mh"],
        notes=("Facility-level answers to the N-SUMHSS question on programs "
               "tailored for LGBTQ+ clients (category SG, code GL). Used only "
               "to flag facilities already carried from the findtreatment.gov "
               "locator; no records are created from this file, because a 2024 "
               "survey row absent from the current locator may be a closed "
               "facility."),
    )

    # index the locator records this pass may touch
    by_name, by_street = defaultdict(set), defaultdict(set)
    for path in sorted((DATA / "sites").rglob("*.yaml")):
        for rec in load_yaml(path) or []:
            if "samhsa/findtreatment" not in (rec.get("sources") or []):
                continue
            addr = rec.get("address") or {}
            city, state = norm(addr.get("city")), (addr.get("state") or "").lower()
            by_name[(nname(rec.get("name")), city, state)].add(rec["id"])
            if addr.get("street"):
                by_street[(nstreet(addr.get("street")), city, state)].add(rec["id"])

    matched, unmatched = set(), 0
    for row in rows:
        city, state = norm(row.get("city")), (row.get("state") or "").lower()
        hit = set()
        for field in ("name1", "name2"):
            key = (nname(row.get(field)), city, state)
            if key[0] and key in by_name:
                hit = by_name[key]
                break
        if not hit:
            key = (nstreet(row.get("street1")), city, state)
            if key[0] and key in by_street:
                hit = by_street[key]
        if hit:
            matched |= hit
        else:
            unmatched += 1

    # Apply as a pure function of the directory: a facility that has dropped its
    # tailored program loses the token on the next run, rather than keeping it
    # because it once qualified.
    added = removed = 0
    for path in sorted((DATA / "sites").rglob("*.yaml")):
        records = load_yaml(path) or []
        changed = False
        for rec in records:
            should = rec["id"] in matched
            has = TOKEN in (rec.get("categories") or [])
            if should and not has:
                rec.setdefault("categories", []).append(TOKEN)
                if source_id not in (rec.get("sources") or []):
                    rec.setdefault("sources", []).append(source_id)
                added += 1
                changed = True
            elif has and not should:
                rec["categories"] = [c for c in rec["categories"] if c != TOKEN]
                rec["sources"] = [s for s in rec.get("sources", []) if s != source_id]
                removed += 1
                changed = True
        if changed:
            dump_yaml([_reflow(r) for r in records], path)

    total = len(rows)
    print(f"nsumhss: {len(matched)} records flagged {TOKEN} "
          f"({added} added, {removed} removed); "
          f"{total - unmatched}/{total} directory rows matched "
          f"({100 * (total - unmatched) / total:.0f}%)")



if __name__ == "__main__":
    main(sys.argv[1:])
