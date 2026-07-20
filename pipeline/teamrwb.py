"""Team Red, White & Blue chapter list -> org records (veterans /
peer-support).

teamrwb.org/find-your-chapter renders the full chapter list inline
(~201 unique groups) as members.teamrwb.org/groups/<id> links titled
"Team RWB <State>[ - <City>]". City-level entries carry no street address —
that is how the org publishes them; the members-site group link is the
record's website. "Team RWB DC/MD/VA" is filed under dc as a regional
group; "Team RWB Overseas" is filed under us. Facts-only re-expression,
attributed (see DATA-RIGHTS.md).

Usage: python3 -m pipeline.teamrwb [--force]
"""
import html
import re
import sys
from collections import Counter

from .emit import Places, replace_records, today, write_source
from .util import Flow, SOURCES, fetch

URL = "https://teamrwb.org/find-your-chapter"

LINK_RE = re.compile(
    r'href="(https://members\.teamrwb\.org/groups/(\d+))"[^>]*>([^<]{2,90})<')

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
    low = " " + " ".join(re.sub(r"[^a-z ]+", " ", text.lower()).split()) + " "
    best, code = "", ""
    for name, c in STATE_NAMES.items():
        if f" {name} " in low and len(name) > len(best):
            best, code = name, c
    return code


def main(argv):
    force = "--force" in argv
    places = Places()
    page = fetch(URL, SOURCES / "teamrwb" / "find-your-chapter.html",
                 force=force).read_text(errors="replace")

    source_id = write_source(
        "teamrwb", "chapter-list",
        kind="directory", publisher="Team Red, White & Blue",
        title="Team RWB find-your-chapter list",
        url=URL, tier="primary",
    )

    records, seen, got = [], set(), Counter()
    for link, gid, raw_name in LINK_RE.findall(page):
        name = " ".join(html.unescape(raw_name).split())
        if not name or gid in seen:
            continue
        seen.add(gid)
        st, area = find_state(name), None
        city = ""
        if " - " in name:
            city = name.split(" - ", 1)[1].strip()
        elif st:
            area = Flow(kind="state", state=st)  # state-level group
        if not st:
            if "dc/md/va" in name.lower():
                st, area = "dc", Flow(kind="regional", name="DC/MD/VA")
            elif "overseas" in name.lower():
                st = "us"
            else:
                print(f"teamrwb: no state for {name!r} — skipped")
                continue
        rec = {
            "_state": st, "_place_slug": "", "_name": name,
            "categories": ["veterans", "peer-support"],
            "parent_org": "us/team-rwb",
            "website": link,
            "external_ids": Flow(teamrwb_group=gid),
        }
        if area:
            rec["service_area"] = area
        if city and st != "us":
            geoid, _ = places.resolve(st, city)
            if geoid:
                rec["place"] = geoid
                got["place"] += 1
        rec["sources"] = [source_id]
        rec["verified"] = Flow(on=today(), method="scrape")
        records.append(rec)

    print(f"enriched {got['place']}/{len(records)} chapters with place")
    if len(records) < 150:
        raise SystemExit(f"teamrwb: only {len(records)} chapters — expected ~201")

    records.append({
        "_state": "us", "_place_slug": "", "_name": "Team Red, White & Blue",
        "id": "us/team-rwb",
        "aliases": ["Team RWB"],
        "categories": ["veterans", "peer-support"],
        "description": "Veteran health and wellness community — local "
                       "chapters host fitness activities and social events "
                       "connecting veterans to their communities.",
        "website": "https://teamrwb.org",
        "service_area": Flow(kind="national"),
        "sources": [source_id],
        "verified": Flow(on=today(), method="scrape"),
    })

    replace_records("orgs", source_id, records)


if __name__ == "__main__":
    main(sys.argv[1:])
