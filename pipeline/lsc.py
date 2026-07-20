"""LSC (Legal Services Corporation) grantee programs -> org records (legal-aid).

The public "Our Grantees" page is a Drupal accordion of bare names whose profile
links are Tableau embeds (no contact detail in HTML). LSC's own "Find Legal Aid"
tool instead loads a static Programs.json (one entry per service area: legal
name, website, phone, fax, Serv_Area_ID like "LA-15") — that's the machine
source used here. Entries dedupe by name to the 129 grantee programs; a few
programs hold multiple service areas (DNA-People's spans AZ and NM). State comes
from the Serv_Area_ID prefix. Facts-only re-expression, attributed.

Usage: python3 -m pipeline.lsc [--force]
"""
import json
import re
import sys

from .emit import replace_records, today, write_source
from .util import Flow, SOURCES, fetch

DATA_URL = "https://www.lsc.gov/themes/lsc/scripts/find-legal-aid-leaflet/Programs.json"
PAGE_URL = "https://www.lsc.gov/grants/our-grantees"

STATES = {
    "al", "ak", "as", "az", "ar", "ca", "co", "ct", "de", "dc", "fl", "ga", "gu",
    "hi", "id", "il", "in", "ia", "ks", "ky", "la", "me", "md", "ma", "mi", "mn",
    "ms", "mo", "mt", "ne", "nv", "nh", "nj", "nm", "ny", "nc", "nd", "mp", "oh",
    "ok", "or", "pa", "pr", "ri", "sc", "sd", "tn", "tx", "ut", "vt", "vi", "va",
    "wa", "wv", "wi", "wy",
}


def norm_phone(raw: str) -> str | None:
    digits = re.sub(r"\D", "", raw or "")
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    if len(digits) == 10:
        return f"{digits[:3]}-{digits[3:6]}-{digits[6:]}"
    return None


def main(argv):
    force = "--force" in argv
    cache = SOURCES / "lsc" / "programs.json"
    entries = json.loads(fetch(DATA_URL, cache, force=force).read_text())

    source_id = write_source(
        "lsc", "grantee-programs",
        kind="directory", publisher="Legal Services Corporation",
        title="LSC grantee programs (Find Legal Aid directory data)",
        url=PAGE_URL, tier="primary",
        notes=f"Program data pulled from the Find Legal Aid tool's dataset at {DATA_URL}; "
              "the our-grantees page itself links only Tableau profile embeds.",
    )

    # dedupe service-area rows into programs, first row wins for contact fields
    programs: dict[str, dict] = {}
    for e in entries:
        name = (e.get("R_Legalname") or "").strip()
        area = (e.get("Serv_Area_ID") or "").strip()
        state = area.split("-")[0].lower()
        if not name or state not in STATES:
            continue  # blank placeholder rows and the upstream "Test REI" entry
        prog = programs.setdefault(name, {"entry": e, "state": state, "areas": []})
        prog["areas"].append(area)

    records = []
    for name, prog in programs.items():
        e = prog["entry"]
        rec = {
            "_state": prog["state"], "_place_slug": "", "_name": name,
            "categories": ["legal-aid"],
            "service_area": Flow(kind="regional", state=prog["state"]),
        }
        website = (e.get("Web_URL") or "").strip()
        if website:
            rec["website"] = website if website.startswith("http") else f"https://{website}"
        phone = norm_phone(e.get("Phone")) or norm_phone(e.get("Local_800"))
        if phone:
            rec["phone"] = phone
        rec["external_ids"] = Flow(lsc=",".join(sorted(prog["areas"])))
        rec["sources"] = [source_id]
        rec["verified"] = Flow(on=today(), method="scrape")
        records.append(rec)

    if len(records) < 100:
        raise SystemExit(f"lsc: only {len(records)} programs — expected ~129; aborting")
    replace_records("orgs", source_id, records)


if __name__ == "__main__":
    main(sys.argv[1:])
