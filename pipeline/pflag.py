"""PFLAG chapter directory -> org records (lgbtq / family-support).

The find-a-chapter page embeds every chapter as a JSON string in its inline
`tmscripts` config object — one GET, no API. Raw page cached under
sources/pflag/. Facts-only re-expression, attributed (see DATA-RIGHTS.md).

Usage: python3 -m pipeline.pflag [--force]
"""
import json
import re
import sys

from .emit import Places, replace_records, today, write_source
from .util import Flow, SOURCES, fetch

URL = "https://pflag.org/findachapter/"

LOC_RE = re.compile(r"^(?P<city>.+?),\s*(?P<state>[A-Z]{2})\s*(?P<zip>\d{5})?(-\d{4})?$")


def parse_location(location: str) -> dict:
    """'115 Gregg Avenue<br>Aiken, SC 29801<br>US' -> address dict."""
    parts = [p.strip() for p in location.split("<br>") if p.strip() and p.strip() != "US"]
    if not parts:
        return {}
    m = LOC_RE.match(parts[-1])
    if not m:
        return {}
    addr = {"city": m["city"], "state": m["state"].lower()}
    if m["zip"]:
        addr["zip"] = m["zip"]
    if len(parts) > 1:
        addr = {"street": ", ".join(parts[:-1]), **addr}
    return addr


def main(argv):
    force = "--force" in argv
    places = Places()
    cache = SOURCES / "pflag" / "findachapter.html"
    html = fetch(URL, cache, force=force).read_text()

    i = html.find("tmscripts = ")
    if i < 0:
        raise SystemExit("pflag: tmscripts config not found — page layout changed")
    config, _ = json.JSONDecoder().raw_decode(html, i + len("tmscripts = "))
    chapters = json.loads(config["chapter_data"])
    if len(chapters) < 200:
        raise SystemExit(f"pflag: only {len(chapters)} chapters — expected ~345; aborting")

    source_id = write_source(
        "pflag", "chapter-directory",
        kind="directory", publisher="PFLAG National",
        title="PFLAG Find a Chapter",
        url=URL, tier="primary",
    )

    records = []
    for ch in chapters:
        name = (ch.get("chapter_name") or "").strip()
        addr = parse_location(ch.get("location") or "")
        st = addr.get("state")
        if not name or not st or st not in places.by_state:
            continue
        geoid, _ = places.resolve(st, addr.get("city", ""))
        rec = {
            "_state": st, "_place_slug": "", "_name": name,
            "categories": ["lgbtq", "family-support", "peer-support"],
            "parent_org": "us/pflag",
            "address": Flow(addr),
        }
        if geoid:
            rec["place"] = geoid
        try:
            rec["geo"] = Flow(lat=round(float(ch["latitude"]), 5),
                              lng=round(float(ch["longitude"]), 5))
        except (KeyError, TypeError, ValueError):
            pass
        for field, key in (("phone", "phone"), ("email", "email")):
            if ch.get(key):
                rec[field] = ch[key].strip()
        website = (ch.get("website") or ch.get("url") or "").strip()
        if website:
            rec["website"] = website
        rec["sources"] = [source_id]
        rec["verified"] = Flow(on=today(), method="scrape")
        records.append(rec)

    # the national umbrella org the chapters point at
    records.append({
        "_state": "us", "_place_slug": "", "_name": "PFLAG National",
        "id": "us/pflag",
        "categories": ["lgbtq", "family-support"],
        "website": "https://pflag.org",
        "service_area": Flow(kind="national"),
        "sources": [source_id],
        "verified": Flow(on=today(), method="scrape"),
    })

    replace_records("orgs", source_id, records)


if __name__ == "__main__":
    main(sys.argv[1:])
