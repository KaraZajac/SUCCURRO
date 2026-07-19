"""BMLT ecosystem (Basic Meeting List Toolkit) -> NA meeting records.

The bmltenabled.org aggregator's /api/v1/rootservers endpoint lists every known
BMLT root server (44 as of 2026-07); each root server's own
client_interface/json/?switcher=GetSearchResults returns its full meeting dump.
The aggregator itself returns [] for a bare GetSearchResults, so we pull from
each root server directly. Raw responses cached under sources/bmlt/ (one file
per server, named by aggregator server id). Non-US servers are fetched but
filtered out by state; a server that fails to fetch/parse is skipped with a
warning rather than aborting the run.

Usage: python3 -m pipeline.bmlt [--force]
"""
import json
import re
import sys

from .emit import Places, replace_records, today, write_source
from .util import Flow, ROOT, SOURCES, get, slugify

AGGREGATOR = "https://aggregator.bmltenabled.org/main_server/api/v1/rootservers"

# weekday_tinyint: 1=Sunday .. 7=Saturday
DAYS = ["sun", "mon", "tue", "wed", "thu", "fri", "sat"]
VENUE_TYPES = {"1": "in-person", "2": "online", "3": "hybrid"}

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

TIME_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
URL_RE = re.compile(r"^https?://\S+$")
ZIP_RE = re.compile(r"^\d{5}(-\d{4})?$")


def fetch_json(url: str, cache, force: bool, timeout: int = 300):
    """Cached JSON GET. Raises SystemExit (from util.get) on network failure."""
    if not cache.exists() or force:
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_bytes(get(url, timeout=timeout))
        print(f"fetched {url} -> {cache.relative_to(ROOT)}")
    return json.loads(cache.read_text())


def norm_state(raw: str, by_state) -> str | None:
    """'TX' / 'tx' / 'Texas' -> 'tx' if it's a registry state, else None."""
    key = (raw or "").strip().lower()
    if len(key) == 2:
        return key if key in by_state else None
    code = STATE_NAMES.get(key)
    return code if code in by_state else None


def parse_time(raw: str) -> str | None:
    """'19:00:00' or '19:00' -> '19:00'; None if malformed."""
    parts = (raw or "").split(":")
    if len(parts) < 2:
        return None
    try:
        hhmm = f"{int(parts[0]):02d}:{int(parts[1]):02d}"
    except ValueError:
        return None
    return hhmm if TIME_RE.match(hhmm) else None


def parse_duration(raw: str) -> int | None:
    parts = (raw or "").split(":")
    if len(parts) < 2:
        return None
    try:
        minutes = int(parts[0]) * 60 + int(parts[1])
    except ValueError:
        return None
    return minutes if 0 < minutes <= 24 * 60 else None


def meeting_format(row: dict) -> str:
    vt = str(row.get("venue_type") or "").strip()
    if vt in VENUE_TYPES:
        return VENUE_TYPES[vt]
    # older servers lack venue_type: virtual link and no street reads as online
    if (row.get("virtual_meeting_link") or "").strip() and \
            not (row.get("location_street") or "").strip():
        return "online"
    return "in-person"


def build_record(row: dict, rs_id: int, places: Places, source_id: str) -> dict | None:
    name = (row.get("meeting_name") or "").strip()
    if not name:
        return None
    st = norm_state(row.get("location_province"), places.by_state)
    if not st:
        return None
    try:
        day = DAYS[int(str(row.get("weekday_tinyint")).strip()) - 1]
    except (ValueError, IndexError):
        return None
    time = parse_time(row.get("start_time"))
    if not time:
        return None

    fmt = meeting_format(row)
    entry = Flow(day=day, time=time)
    duration = parse_duration(row.get("duration_time"))
    if duration:
        entry["duration_min"] = duration

    rec = {
        "_state": st, "_place_slug": "online", "_name": name,
        "program": "na",
        "categories": ["recovery-meeting"],
        "schedule": [entry],
        "format": fmt,
    }

    types = []
    for code in (row.get("formats") or "").split(","):
        token = slugify(code.strip())
        if token and token not in types:
            types.append(token)
        if len(types) >= 8:
            break
    if types:
        rec["types"] = types

    city = (row.get("location_municipality") or "").strip()
    if fmt != "online":
        geoid, place_slug = places.resolve(st, city)
        geo = None
        try:
            lat, lng = float(row["latitude"]), float(row["longitude"])
            if (lat, lng) != (0.0, 0.0) and abs(lat) <= 90 and abs(lng) <= 180:
                geo = Flow(lat=round(lat, 5), lng=round(lng, 5))
        except (KeyError, TypeError, ValueError):
            pass
        if not geoid and geo:
            near = places.nearest(geo["lat"], geo["lng"])
            if near and near[0] == st:
                _, geoid, place_slug = near
        rec["_place_slug"] = place_slug
        venue_name = (row.get("location_text") or "").strip()
        if venue_name:
            rec["venue_name"] = venue_name
        if city:  # address schema requires city + state
            venue = {"street": (row.get("location_street") or "").strip(),
                     "city": city, "state": st}
            zipc = (row.get("location_postal_code_1") or "").strip()
            if ZIP_RE.match(zipc):
                venue["zip"] = zipc
            rec["venue"] = Flow({k: v for k, v in venue.items() if v})
        if geoid:
            rec["place"] = geoid
        if geo:
            rec["geo"] = geo

    link = (row.get("virtual_meeting_link") or "").strip()
    if URL_RE.match(link):
        rec["conference_url"] = link
    notes = (row.get("comments") or "").strip()
    if notes and len(notes) <= 400:
        rec["notes"] = notes
    rec["external_ids"] = Flow(bmlt=f"{rs_id}:{row.get('id_bigint')}")
    rec["sources"] = [source_id]
    rec["verified"] = Flow(on=today(), method="api")
    return rec


def main(argv):
    force = "--force" in argv
    places = Places()
    cache_dir = SOURCES / "bmlt"

    servers = fetch_json(AGGREGATOR, cache_dir / "rootservers.json", force)
    if not isinstance(servers, list) or len(servers) < 30:
        raise SystemExit(f"bmlt: rootservers list looks wrong ({len(servers)} entries)")

    source_id = write_source(
        "bmlt", "aggregator",
        kind="api-feed", publisher="BMLT (bmltenabled.org)",
        title="Basic Meeting List Toolkit aggregator — NA meetings",
        url="https://aggregator.bmltenabled.org/", tier="primary",
    )

    records, seen_ext, seen_exact = [], set(), set()
    per_server, skipped_servers = {}, []
    for rs in sorted(servers, key=lambda r: r["id"]):
        rs_id, rs_url = rs["id"], rs["url"].rstrip("/")
        endpoint = f"{rs_url}/client_interface/json/?switcher=GetSearchResults"
        try:
            rows = fetch_json(endpoint, cache_dir / f"server-{rs_id}.json", force)
        except (SystemExit, json.JSONDecodeError) as e:
            print(f"WARNING: skipping root server {rs_id} ({rs['name']}): {e}")
            skipped_servers.append(f"{rs_id} {rs['name']}")
            continue
        if isinstance(rows, dict):
            rows = rows.get("meetings") or []
        if not isinstance(rows, list):
            print(f"WARNING: skipping root server {rs_id} ({rs['name']}): unexpected payload")
            skipped_servers.append(f"{rs_id} {rs['name']}")
            continue
        kept = 0
        for row in rows:
            if not isinstance(row, dict) or str(row.get("published", "1")) == "0":
                continue
            rec = build_record(row, rs_id, places, source_id)
            if rec is None:
                continue
            ext = rec["external_ids"]["bmlt"]
            entry = rec["schedule"][0]
            city = (row.get("location_municipality") or "").strip().lower()
            exact = (rec["_name"].lower(), entry["day"], entry["time"],
                     rec["_state"], city)
            if ext in seen_ext or exact in seen_exact:
                continue
            seen_ext.add(ext)
            seen_exact.add(exact)
            records.append(rec)
            kept += 1
        if kept:
            per_server[f"{rs_id} {rs['name']}"] = kept

    if len(records) < 15000:
        raise SystemExit(f"bmlt: only {len(records)} US meetings — expected 15k+; aborting")

    top = sorted(per_server.items(), key=lambda kv: -kv[1])[:5]
    print("top servers:", ", ".join(f"{k}: {v}" for k, v in top))
    if skipped_servers:
        print(f"skipped servers: {', '.join(skipped_servers)}")
    replace_records("meetings", source_id, records)


if __name__ == "__main__":
    main(sys.argv[1:])
