"""AFSP Find a Support Group API -> org records (suicide-loss support
groups, suicide-prevention / peer-support).

The finder posts to a Heroku backend that fronts AFSP's DatoCMS support-
group collection. Contract (verified 2026-07): POST /support-groups-find
with JSON {"country": "United States of America", "zip": "10001",
"radius": "100", "type": <t>} where <t> is one of in_person_group |
local_online_group | nationwide_online_group (the nationwide form omits
zip/radius). Any other type value crashes the dyno (503) — only these
exact shapes are sent. Records carry no schedules, so they are org
records, not meetings.

Enumeration: a ~120-zip national spread (one zip per major metro per
state, chosen programmatically — metro geo from data/places/, nearest
ZCTA centroid from data/crosswalk/zips.yaml) at radius 100 for the two
local types, plus one nationwide call; deduped by the stable DatoCMS
item id (external_ids.datocms). Responses cache under
sources/afsp/groups/. The dyno is fragile: requests are throttled, 503s
retried once after a long pause, and the run aborts after 10 consecutive
failures.

FACTS-ONLY: facilitator personal names/emails/phones are never recorded
(the API's contact fields are personal facilitator contacts, so they are
all dropped). Kept fields: group name, sponsoring organization /
demographic / fee (description), website, city/state/zip. Attributed
re-expression (see DATA-RIGHTS.md).

Usage: python3 -m pipeline.afspgroups [--force]
"""
import json
import re
import sys
import time
from collections import Counter
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .emit import Places, norm, replace_records, today, write_source
from .util import DATA, Flow, SOURCES, UA, load_yaml

API = "https://afsp-support-groups-700295b25974.herokuapp.com/support-groups-find"
FIND_URL = "https://afsp.org/find-a-support-group/"
COUNTRY = "United States of America"
RADIUS = "100"
THROTTLE = 2.0      # the dyno crashes easily — be gentle
RETRY_WAIT = 30.0   # a 503 usually means the dyno is restarting
MAX_STREAK = 10

# One zip per major metro per state (~120 total): the metro's registry
# place gives the coordinate, the nearest ZCTA centroid gives the zip.
# A few consolidated cities use their registry names or an in-metro
# suburb that is in the registry (Lawrence = Indianapolis metro,
# Belle Meade = Nashville metro).
METROS = {
    "al": ["Birmingham", "Mobile"], "ak": ["Anchorage"],
    "az": ["Phoenix", "Tucson", "Flagstaff"],
    "ar": ["Little Rock", "Fayetteville"],
    "ca": ["Los Angeles", "San Francisco", "San Diego", "Sacramento",
           "Fresno"],
    "co": ["Denver", "Grand Junction", "Colorado Springs"],
    "ct": ["Hartford", "Bridgeport"], "dc": ["Washington"],
    "de": ["Wilmington"],
    "fl": ["Miami", "Orlando", "Tampa", "Jacksonville", "Tallahassee"],
    "ga": ["Atlanta", "Savannah", "Macon-Bibb County"],
    "hi": ["Urban Honolulu"], "id": ["Boise City", "Idaho Falls"],
    "il": ["Chicago", "Springfield", "Rockford"],
    "in": ["Lawrence", "Fort Wayne", "Evansville"],
    "ia": ["Des Moines", "Cedar Rapids"], "ks": ["Wichita", "Topeka"],
    "ky": ["Louisville", "Lexington-Fayette urban county"],
    "la": ["New Orleans", "Shreveport"], "me": ["Portland", "Bangor"],
    "md": ["Baltimore", "Salisbury"], "ma": ["Boston", "Springfield"],
    "mi": ["Detroit", "Grand Rapids", "Marquette"],
    "mn": ["Minneapolis", "Duluth", "Moorhead"],
    "ms": ["Jackson", "Gulfport"],
    "mo": ["Kansas City", "St. Louis", "Springfield"],
    "mt": ["Billings", "Missoula"], "ne": ["Omaha", "North Platte"],
    "nv": ["Las Vegas", "Reno"], "nh": ["Manchester"],
    "nj": ["Newark", "Trenton"], "nm": ["Albuquerque", "Las Cruces"],
    "ny": ["New York", "Buffalo", "Albany", "Syracuse"],
    "nc": ["Charlotte", "Raleigh", "Asheville"],
    "nd": ["Fargo", "Bismarck"],
    "oh": ["Columbus", "Cleveland", "Cincinnati"],
    "ok": ["Oklahoma City", "Tulsa"], "or": ["Portland", "Medford", "Bend"],
    "pa": ["Philadelphia", "Pittsburgh", "Harrisburg"],
    "pr": ["San Juan zona urbana"], "ri": ["Providence"],
    "sc": ["Columbia", "Charleston"], "sd": ["Sioux Falls", "Rapid City"],
    "tn": ["Belle Meade", "Memphis", "Knoxville"],
    "tx": ["Houston", "Dallas", "San Antonio", "El Paso", "Lubbock"],
    "ut": ["Salt Lake City", "St. George"], "vt": ["Burlington"],
    "va": ["Richmond", "Norfolk", "Roanoke"],
    "wa": ["Seattle", "Spokane", "Vancouver"],
    "wv": ["Charleston", "Morgantown"],
    "wi": ["Milwaukee", "Madison", "Green Bay"],
    "wy": ["Cheyenne", "Casper"],
}

STATE_CODES = {
    "alabama": "al", "alaska": "ak", "arizona": "az", "arkansas": "ar",
    "california": "ca", "colorado": "co", "connecticut": "ct",
    "delaware": "de", "district of columbia": "dc", "florida": "fl",
    "georgia": "ga", "hawaii": "hi", "idaho": "id", "illinois": "il",
    "indiana": "in", "iowa": "ia", "kansas": "ks", "kentucky": "ky",
    "louisiana": "la", "maine": "me", "maryland": "md",
    "massachusetts": "ma", "michigan": "mi", "minnesota": "mn",
    "mississippi": "ms", "missouri": "mo", "montana": "mt",
    "nebraska": "ne", "nevada": "nv", "new hampshire": "nh",
    "new jersey": "nj", "new mexico": "nm", "new york": "ny",
    "north carolina": "nc", "north dakota": "nd", "ohio": "oh",
    "oklahoma": "ok", "oregon": "or", "pennsylvania": "pa",
    "puerto rico": "pr", "rhode island": "ri", "south carolina": "sc",
    "south dakota": "sd", "tennessee": "tn", "texas": "tx", "utah": "ut",
    "vermont": "vt", "virginia": "va", "washington": "wa",
    "west virginia": "wv", "wisconsin": "wi", "wyoming": "wy",
}
VALID_CODES = set(STATE_CODES.values())

NO_FEE_RE = re.compile(r"^\s*(no\b|none\b|free\b|\$?\s*0+(\.0+)?\s*$)", re.I)

# meeting-city values that aren't cities (virtual notes, bare state names)
CITY_JUNK_RE = re.compile(r"virtual|zoom|online|^n/?a$|^tbd$|^none$", re.I)


def state_code(raw: str) -> str:
    """'New York' | 'NJ' -> code; '' if unrecognized."""
    text = (raw or "").strip().lower()
    if text in STATE_CODES:
        return STATE_CODES[text]
    if len(text) == 2 and text in VALID_CODES:
        return text
    return ""


def pick_zips(zips: dict) -> list[tuple[str, str, str]]:
    """(state, metro, zip) per METROS entry: the ZCTA centroid nearest the
    metro's registry place. Fails loud on an unresolvable metro name."""
    ztable = [(z, lat, lng) for z, (lat, lng) in zips.items()]
    picked, seen = [], set()
    for st in sorted(METROS):
        index = {}
        for rec in load_yaml(DATA / "places" / f"{st}.yaml"):
            index.setdefault(norm(rec["name"]), rec)
        for city in METROS[st]:
            rec = index.get(norm(city))
            if not rec:
                raise SystemExit(f"afspgroups: metro {city!r} not in "
                                 f"data/places/{st}.yaml")
            lat, lng = rec["geo"]["lat"], rec["geo"]["lng"]
            best = min(ztable, key=lambda t: (t[1] - lat) ** 2
                       + ((t[2] - lng) * 0.78) ** 2)
            if best[0] not in seen:
                seen.add(best[0])
                picked.append((st, city, best[0]))
    return picked


_streak = 0


def post(payload: dict, cache, force: bool):
    """Cached, throttled POST. Retries once on 503 (dyno restart), skips
    (returns None) on persistent failure, aborts after MAX_STREAK
    consecutive failed payloads."""
    global _streak
    if cache.exists() and not force:
        return json.loads(cache.read_text())
    body = json.dumps(payload).encode()
    for attempt in (1, 2):
        time.sleep(THROTTLE)
        req = Request(API, data=body, headers={
            "User-Agent": UA, "Content-Type": "application/json"})
        try:
            with urlopen(req, timeout=120) as resp:
                raw = resp.read()
            data = json.loads(raw)
            cache.parent.mkdir(parents=True, exist_ok=True)
            cache.write_bytes(raw)
            _streak = 0
            print(f"fetched {cache.name} ({len(data)} items)")
            return data
        except HTTPError as e:
            if e.code == 503 and attempt == 1:
                print(f"afspgroups: 503 for {cache.name} — waiting "
                      f"{RETRY_WAIT:.0f}s for the dyno, retrying once")
                time.sleep(RETRY_WAIT)
                continue
            err = e
        except (URLError, TimeoutError, json.JSONDecodeError) as e:
            err = e
        break
    _streak += 1
    if _streak >= MAX_STREAK:
        raise SystemExit(f"afspgroups: {MAX_STREAK} consecutive failures "
                         f"(last: {cache.name}: {err}) — dyno is down, "
                         "aborting")
    print(f"afspgroups: FAILED {cache.name} ({err}) — skipped")
    return None


def sentence(text: str) -> str:
    text = " ".join(text.split())
    return text if text.endswith((".", "!", "?")) else text + "."


def build(item: dict, national: bool, source_id: str,
          zip_state) -> dict | None:
    name = " ".join((item.get("support_group_name") or "").split())
    if not name:
        return None
    st = state_code(item.get("support_group_meeting_us_state_or_territory"))
    if not st:
        # a handful of records leave the state blank or "Not Applicable"
        # but carry a meeting zip — recover the state from its centroid
        zm = re.match(r"\d{5}", (item.get("support_group_meeting_zip_code")
                                 or "").strip())
        if zm:
            st = zip_state(zm.group(0))
    if national:
        parts = ["Nationwide online suicide-loss (bereavement) support "
                 "group listed in AFSP's Find a Support Group directory."]
    else:
        if not st:
            return None  # unrecognized state/territory — caller reports
        parts = ["Suicide-loss (bereavement) support group listed in "
                 "AFSP's Find a Support Group directory."]
    sponsor = " ".join(
        (item.get("support_group_hosting_sponsoring_organization") or "").split())
    if sponsor:
        parts.append(sentence(sponsor) if sponsor.lower().startswith("sponsor")
                     else sentence(f"Sponsored by {sponsor}"))
    demog = " ".join((item.get("support_group_demographic") or "").split())
    if demog:
        parts.append(sentence(f"Open to: {demog}"))
    fee = " ".join((item.get("support_group_fee") or "").split())
    if not item.get("support_group_has_fee") or NO_FEE_RE.match(fee):
        parts.append("No fee.")
    elif fee:
        parts.append(sentence(f"Fee: {fee}"))
    else:
        parts.append("Fee charged.")

    rec = {"_state": "us" if national else st, "_place_slug": "",
           "_name": name,
           "categories": ["suicide-prevention", "peer-support"],
           "description": " ".join(parts)}
    site = (item.get("support_group_website") or "").strip()
    if site and not site.startswith(("http://", "https://")):
        site = "https://" + site if "." in site and " " not in site else ""
    if site:
        rec["website"] = site
    if not national:
        city = " ".join((item.get("support_group_meeting_city") or "").split())
        if city and (CITY_JUNK_RE.search(city) or state_code(city)):
            city = ""  # "Virtual", "Meeting via Zoom", bare state names
        if city:
            addr = Flow(city=city, state=st)
            z = (item.get("support_group_meeting_zip_code") or "").strip()
            if re.match(r"^\d{5}(-\d{4})?$", z):
                addr["zip"] = z
            rec["address"] = addr
    else:
        rec["service_area"] = Flow(kind="national")
    rec["external_ids"] = Flow(datocms=item["id"])
    rec["sources"] = [source_id]
    rec["verified"] = Flow(on=today(), method="api")
    return rec


def main(argv):
    force = "--force" in argv
    zips = load_yaml(DATA / "crosswalk" / "zips.yaml")
    spread = pick_zips(zips)
    print(f"zip spread: {len(spread)} zips across {len(METROS)} states")

    places = Places()

    def zip_state(z5: str) -> str:
        coords = zips.get(z5)
        if not coords:
            return ""
        hit = places.nearest(coords[0], coords[1])
        return hit[0] if hit else ""

    source_id = write_source(
        "afsp", "support-groups-api",
        kind="api-feed",
        publisher="American Foundation for Suicide Prevention",
        title="AFSP Find a Support Group API (national zip-radius sweep)",
        url=FIND_URL, tier="primary",
    )

    groups = SOURCES / "afsp" / "groups"
    by_id: dict[str, dict] = {}
    failed = []
    for st, city, z in spread:
        for typ, stem in (("in_person_group", "in-person"),
                          ("local_online_group", "local-online")):
            data = post({"country": COUNTRY, "zip": z, "radius": RADIUS,
                         "type": typ}, groups / f"{stem}-{z}.json", force)
            if data is None:
                failed.append(f"{stem}-{z} ({st} {city})")
                continue
            for item in data:
                by_id.setdefault(item["id"], item)

    national = post({"country": COUNTRY, "type": "nationwide_online_group"},
                    groups / "nationwide.json", force)
    if national is None:
        raise SystemExit("afspgroups: nationwide_online_group call failed — "
                         "national records would be silently missing")
    national_ids = {item["id"] for item in national}
    for item in national:
        by_id.setdefault(item["id"], item)

    if failed:
        print(f"afspgroups: {len(failed)} query(ies) failed and were "
              f"skipped: {', '.join(failed)}")

    records, skipped = [], Counter()
    for gid, item in by_id.items():
        rec = build(item, gid in national_ids, source_id, zip_state)
        if rec is None:
            skipped["no-name-or-state"] += 1
            print(f"afspgroups: skip {gid}: name="
                  f"{item.get('support_group_name')!r} state="
                  f"{item.get('support_group_meeting_us_state_or_territory')!r}")
            continue
        records.append(rec)

    if skipped:
        print("skipped:", dict(skipped))
    n_nat = sum(1 for r in records if r["_state"] == "us")
    n_states = len({r["_state"] for r in records}) - (1 if n_nat else 0)
    print(f"{len(records)} distinct groups ({n_nat} nationwide-online) "
          f"across {n_states} states")
    if len(records) < 150:
        raise SystemExit(f"afspgroups: only {len(records)} groups — "
                         "floor is 150")
    replace_records("orgs", source_id, records)


if __name__ == "__main__":
    main(sys.argv[1:])
