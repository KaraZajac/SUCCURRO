"""Catholic Charities USA member agencies -> org records (family-support).

The find-a-local-agency page embeds the whole agency locator dataset in an
inline <script type="application/json"> blob ({"data": [...]}, one object per
agency: title, address, city, state, zip, phone, email, website_url, lat/lng,
upstream id). No AJAX endpoint needed — one GET. Three territory entries carry
blank/odd state fields (Puerto Rico, U.S. Virgin Islands, Saipan) and are
patched from their ZIP/name. Facts-only re-expression, attributed.

Usage: python3 -m pipeline.ccusa [--force]
"""
import json
import re
import sys

from .emit import Places, replace_records, today, write_source
from .util import Flow, SOURCES, fetch

URL = "https://www.catholiccharitiesusa.org/about-us/find-a-local-agency/"

BLOB_RE = re.compile(r'<script type="application/json">(.*?)</script>', re.S)

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


def resolve_state(a: dict) -> str | None:
    state = (a.get("state") or "").strip().lower()
    if state in STATES:
        return state
    # territory entries with blank/odd state fields, patched from ZIP/name
    zip_code = (a.get("zip_code") or "").strip()
    if state == "saipan":
        return "mp"
    if zip_code.startswith(("006", "007", "009")):
        return "pr"
    if zip_code.startswith("008"):
        return "vi"
    return None


def main(argv):
    force = "--force" in argv
    places = Places()
    page = fetch(URL, SOURCES / "ccusa" / "find-a-local-agency.html", force=force).read_text()

    agencies = None
    for m in BLOB_RE.finditer(page):
        try:
            blob = json.loads(m.group(1))
        except ValueError:
            continue
        if isinstance(blob, dict) and isinstance(blob.get("data"), list) and blob["data"]:
            agencies = blob["data"]
            break
    if agencies is None:
        raise SystemExit("ccusa: embedded agency JSON blob not found — page layout changed")

    source_id = write_source(
        "ccusa", "agency-locator",
        kind="directory", publisher="Catholic Charities USA",
        title="CCUSA Find a Local Agency",
        url=URL, tier="primary",
    )

    records, skipped = [], 0
    for a in agencies:
        name = (a.get("title") or "").strip()
        state = resolve_state(a)
        if not name or not state:
            skipped += 1
            continue
        addr = {"city": (a.get("city") or "").strip(), "state": state}
        street = ", ".join(p.strip() for p in
                           (a.get("address"), a.get("apartment_or_suite")) if p and p.strip())
        if street:
            addr = {"street": street, **addr}
        zip_code = (a.get("zip_code") or "").strip()
        if re.fullmatch(r"\d{5}(-\d{4})?", zip_code):
            addr["zip"] = zip_code
        if not addr["city"]:
            skipped += 1
            continue
        rec = {
            "_state": state, "_place_slug": "", "_name": name,
            "categories": ["family-support", "financial"],
            "parent_org": "us/catholic-charities-usa",
            "address": Flow(addr),
        }
        geoid, _ = places.resolve(state, addr["city"])
        if geoid:
            rec["place"] = geoid
        try:
            lat, lng = float(a["latitude"]), float(a["longitude"])
            if -90 <= lat <= 90 and -180 <= lng <= 180:  # a few upstream rows lack decimal points
                rec["geo"] = Flow(lat=round(lat, 5), lng=round(lng, 5))
        except (KeyError, TypeError, ValueError):
            pass
        phone = norm_phone(a.get("phone"))
        if phone:
            rec["phone"] = phone
        email = (a.get("email") or "").strip()
        if email:
            rec["email"] = email
        website = (a.get("website_url") or "").strip()
        if website:
            rec["website"] = website if website.startswith("http") else f"https://{website}"
        if a.get("id"):
            rec["external_ids"] = Flow(ccusa=str(a["id"]))
        rec["sources"] = [source_id]
        rec["verified"] = Flow(on=today(), method="scrape")
        records.append(rec)
    if skipped:
        print(f"skipped {skipped} agencies without resolvable name/state/city")

    records.append({
        "_state": "us", "_place_slug": "", "_name": "Catholic Charities USA",
        "id": "us/catholic-charities-usa",
        "categories": ["family-support", "financial"],
        "website": "https://www.catholiccharitiesusa.org",
        "service_area": Flow(kind="national"),
        "sources": [source_id],
        "verified": Flow(on=today(), method="scrape"),
    })

    if len(records) < 130:
        raise SystemExit(f"ccusa: only {len(records)} records — expected ~169; aborting")
    replace_records("orgs", source_id, records)


if __name__ == "__main__":
    main(sys.argv[1:])
