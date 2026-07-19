"""Feeding America member food bank directory -> org records (food-bank).

The find-your-local-foodbank page is backed by an undocumented JSON API at
/ws-api/GetAllOrganizations returning {"Organization": [...]}; orgFields trims
the response (ListFipsCounty alone is ~90% of the payload and unused here).
Every member record carries a full MailAddress incl. Latitude/Longitude, a
dotted phone, and a scheme-less URL. Raw pull cached under sources/feedingamerica/.
Facts-only re-expression, attributed (see DATA-RIGHTS.md).

Usage: python3 -m pipeline.feedingamerica [--force]
"""
import json
import re
import sys

from .emit import Places, replace_records, today, write_source
from .util import Flow, SOURCES, fetch

API_URL = ("https://www.feedingamerica.org/ws-api/GetAllOrganizations"
           "?orgFields=OrganizationID,FullName,MailAddress,URL,Phone,AgencyURL")

ZIP_RE = re.compile(r"^\d{5}$")


def norm_phone(raw: str) -> str:
    """'907.272.3663' -> '907-272-3663'; anything non-US-10-digit passes through."""
    digits = re.sub(r"\D", "", raw)
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    if len(digits) == 10:
        return f"{digits[:3]}-{digits[3:6]}-{digits[6:]}"
    return raw.strip()


def norm_url(raw: str) -> str:
    """The feed's URLs are scheme-less ('www.foodbankofalaska.org/')."""
    raw = raw.strip()
    return raw if "://" in raw else f"https://{raw}"


def main(argv):
    force = "--force" in argv
    places = Places()
    cache = SOURCES / "feedingamerica" / "GetAllOrganizations.json"
    banks = json.loads(fetch(API_URL, cache, force=force).read_text())["Organization"]
    if len(banks) < 150:
        raise SystemExit(f"feedingamerica: only {len(banks)} banks — expected ~198; aborting")

    source_id = write_source(
        "feedingamerica", "member-directory",
        kind="api-feed", publisher="Feeding America",
        title="Feeding America member food bank directory",
        url="https://www.feedingamerica.org/find-your-local-foodbank", tier="primary",
    )

    records = []
    for bank in banks:
        name = (bank.get("FullName") or "").strip()
        mail = bank.get("MailAddress") or {}
        st = (mail.get("State") or "").strip().lower()
        if not name or st not in places.by_state:
            continue
        addr = {}
        if (mail.get("Address1") or "").strip():
            addr["street"] = mail["Address1"].strip()
        if (mail.get("Address2") or "").strip():
            addr["street2"] = mail["Address2"].strip()
        addr["city"] = (mail.get("City") or "").strip()
        addr["state"] = st
        if ZIP_RE.match((mail.get("Zip") or "").strip()):
            addr["zip"] = mail["Zip"].strip()
        geoid, _ = places.resolve(st, addr["city"])
        rec = {
            "_state": st, "_place_slug": "", "_name": name,
            "categories": ["food-bank"],
            "parent_org": "us/feeding-america",
            "address": Flow(addr),
        }
        if geoid:
            rec["place"] = geoid
        try:
            rec["geo"] = Flow(lat=round(float(mail["Latitude"]), 5),
                              lng=round(float(mail["Longitude"]), 5))
        except (KeyError, TypeError, ValueError):
            pass
        if (bank.get("Phone") or "").strip():
            rec["phone"] = norm_phone(bank["Phone"])
        if (bank.get("URL") or "").strip():
            rec["website"] = norm_url(bank["URL"])
        rec["service_area"] = Flow(kind="regional")
        rec["external_ids"] = Flow(feeding_america=str(bank["OrganizationID"]))
        rec["sources"] = [source_id]
        rec["verified"] = Flow(on=today(), method="api")
        records.append(rec)

    # the national umbrella org the member banks point at
    records.append({
        "_state": "us", "_place_slug": "", "_name": "Feeding America",
        "id": "us/feeding-america",
        "categories": ["food-bank"],
        "website": "https://www.feedingamerica.org",
        "service_area": Flow(kind="national"),
        "sources": [source_id],
        "verified": Flow(on=today(), method="api"),
    })

    replace_records("orgs", source_id, records)


if __name__ == "__main__":
    main(sys.argv[1:])
