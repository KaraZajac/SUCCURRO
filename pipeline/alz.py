"""Alzheimer's Association chapter search API -> org records (seniors /
family-support).

POST alz.org/api/chapter/search accepts {"state": "XX"} as well as the
zip form the site UI uses, so the pull enumerates all states + DC + PR
directly (one POST each, throttled, cached under sources/alz/) and dedupes
by chapter url — multi-state chapters (e.g. Desert Southwest) come back
under each state they serve and are filed under the first state that
returned them, with the extra states noted via service_area kind=regional.
Each item carries title, site path (url), and an "Offices in: ..." line
used as the description. Facts-only re-expression, attributed (see
DATA-RIGHTS.md).

Usage: python3 -m pipeline.alz [--force]
"""
import json
import re
import sys
import time
from collections import Counter
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .emit import Places, replace_records, today, write_source
from .util import Flow, SOURCES, UA

API = "https://www.alz.org/api/chapter/search"
FIND_URL = "https://www.alz.org/local_resources/find_your_local_chapter"

STATE_NAMES = {
    "alabama": "al", "alaska": "ak", "arizona": "az", "arkansas": "ar",
    "california": "ca", "colorado": "co", "connecticut": "ct", "delaware": "de",
    "district of columbia": "dc", "florida": "fl", "georgia": "ga",
    "hawaii": "hi", "idaho": "id", "illinois": "il", "indiana": "in",
    "iowa": "ia", "kansas": "ks", "kentucky": "ky", "louisiana": "la",
    "maine": "me", "maryland": "md", "massachusetts": "ma", "michigan": "mi",
    "minnesota": "mn", "mississippi": "ms", "missouri": "mo", "montana": "mt",
    "nebraska": "ne", "nevada": "nv", "new hampshire": "nh", "new jersey": "nj",
    "new mexico": "nm", "new york": "ny", "north carolina": "nc",
    "north dakota": "nd", "ohio": "oh", "oklahoma": "ok", "oregon": "or",
    "pennsylvania": "pa", "puerto rico": "pr", "rhode island": "ri",
    "south carolina": "sc", "south dakota": "sd", "tennessee": "tn",
    "texas": "tx", "utah": "ut", "vermont": "vt", "virginia": "va",
    "washington": "wa", "west virginia": "wv", "wisconsin": "wi",
    "wyoming": "wy",
}


def find_state(text: str) -> str:
    """Longest US state name mentioned in the text wins."""
    low = " " + " ".join(re.sub(r"[^a-z ]+", " ", text.lower()).split()) + " "
    best, code = "", ""
    for name, c in STATE_NAMES.items():
        if f" {name} " in low and len(name) > len(best):
            best, code = name, c
    return code


STATES = [
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "DC", "FL", "GA", "HI",
    "ID", "IL", "IN", "IA", "KS", "KY", "LA", "ME", "MD", "MA", "MI", "MN",
    "MS", "MO", "MT", "NE", "NV", "NH", "NJ", "NM", "NY", "NC", "ND", "OH",
    "OK", "OR", "PA", "PR", "RI", "SC", "SD", "TN", "TX", "UT", "VT", "VA",
    "WA", "WV", "WI", "WY",
]


def post_search(state: str, force: bool):
    """Cached, throttled POST {"state": ...} -> parsed JSON."""
    cache = SOURCES / "alz" / f"search-{state.lower()}.json"
    if cache.exists() and not force:
        return json.loads(cache.read_text())
    time.sleep(1.0)  # polite: one request per second
    req = Request(API, data=json.dumps({"state": state}).encode(),
                  headers={"User-Agent": UA, "Content-Type": "application/json"})
    try:
        with urlopen(req, timeout=60) as resp:
            body = resp.read()
    except (HTTPError, URLError, TimeoutError) as e:
        raise SystemExit(f"alz: POST failed for {state} ({e})")
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_bytes(body)
    print(f"fetched chapter search for {state}")
    return json.loads(body)


def main(argv):
    force = "--force" in argv
    places = Places()
    source_id = write_source(
        "alz", "chapter-search",
        kind="api-feed", publisher="Alzheimer's Association",
        title="Alzheimer's Association chapter search API (state enumeration)",
        url=FIND_URL, tier="primary",
    )

    by_url: dict[str, dict] = {}
    for state in STATES:
        data = post_search(state, force)
        for item in data.get("items") or []:
            path = (item.get("url") or "").strip()
            title = (item.get("title") or "").strip()
            if not path or not title:
                print(f"alz: malformed item under {state}: {item!r} — skipped")
                continue
            entry = by_url.setdefault(path, {"item": item, "states": []})
            entry["states"].append(state.lower())

    if len(by_url) < 50:
        raise SystemExit(f"alz: only {len(by_url)} distinct chapters — expected ~75")

    records, got = [], Counter()
    for path, entry in by_url.items():
        item, states = entry["item"], entry["states"]
        title = item["title"].strip()
        name = title if "chapter" in title.lower() else f"{title} Chapter"
        if not name.lower().startswith("alzheimer"):
            name = f"Alzheimer's Association {name}"
        # multi-state chapters: prefer the state the title names over
        # enumeration order (e.g. "Washington State Chapter" seen from ID)
        st = find_state(title) if len(states) > 1 else ""
        if st not in states:
            st = states[0]
        rec = {
            "_state": st, "_place_slug": "", "_name": name,
            "categories": ["seniors", "family-support"],
            "parent_org": "us/alzheimers-association",
            "website": "https://www.alz.org" + path
            if path.startswith("/") else path,
        }
        desc = (item.get("description") or "").strip()
        if desc:
            rec["description"] = desc
        if len(states) > 1:
            rec["service_area"] = Flow(kind="regional",
                                       name="/".join(s.upper() for s in states))
            got["multi-state"] += 1
        m = re.match(r"Offices in:\s*(.+)", desc)
        if m:
            city = m.group(1).split(",")[0].strip()
            geoid, _ = places.resolve(st, city)
            if geoid:
                rec["place"] = geoid
                got["place"] += 1
        rec["external_ids"] = Flow(alz_site_path=path)
        rec["sources"] = [source_id]
        rec["verified"] = Flow(on=today(), method="api")
        records.append(rec)

    print(f"{len(records)} chapters ({got['multi-state']} multi-state); "
          f"place resolved for {got['place']}")

    records.append({
        "_state": "us", "_place_slug": "", "_name": "Alzheimer's Association",
        "id": "us/alzheimers-association",
        "categories": ["seniors", "family-support"],
        "description": "Care and support for people living with Alzheimer's "
                       "and other dementia and their caregivers — local "
                       "chapters offer support groups, education programs, "
                       "and care consultations. Free 24/7 Helpline "
                       "800-272-3900.",
        "website": "https://www.alz.org",
        "phone": "800-272-3900",
        "service_area": Flow(kind="national"),
        "sources": [source_id],
        "verified": Flow(on=today(), method="api"),
    })

    replace_records("orgs", source_id, records)


if __name__ == "__main__":
    main(sys.argv[1:])
