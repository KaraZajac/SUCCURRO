"""AA meetings from TSML feeds -> meeting records (recovery-meeting).

Harvests every feed in pipeline/curated/feeds.yaml (12 Step Meeting List
WordPress JSON: day 0=Sunday, attendance_option, formatted_address, types).
One source record per feed (aa/<feed-id>); the module owns all records citing
the "aa/" prefix, so feeds later dropped from the registry are cleaned up on
the next run. Adjacent intergroups list overlapping meetings — exact
(name, day, time, city) dedup across feeds handles that.

Usage: python3 -m pipeline.tsml [--force]
"""
import json
import re
import sys
from pathlib import Path

from .emit import Places, replace_records, today, write_source
from .util import BROWSER_UA, DATA, Flow, ROOT, SOURCES, UA, fetch, load_yaml, slugify

FEEDS = ROOT / "pipeline" / "curated" / "feeds.yaml"

DAYS = ("sun", "mon", "tue", "wed", "thu", "fri", "sat")
FORMATS = {"in_person": "in-person", "online": "online", "hybrid": "hybrid"}
TIME_RE = re.compile(r"^([01]?\d|2[0-3]):([0-5]\d)")
URL_RE = re.compile(r"^https?://\S+$")
ZIP_RE = re.compile(r"^\d{5}")
# "700 Whatever St, Washington, DC 20001, USA" / "City, ST, USA"
ADDR_RE = re.compile(
    r"(?:^|,\s*)(?P<city>[^,]+),\s*(?P<state>[A-Z]{2})(?:\s+(?P<zip>\d{5}))?"
    r"(?:-\d{4})?,\s*USA$")


def in_us_bounds(lat, lng):
    return 17.5 <= lat <= 71.5 and -180.0 <= lng <= -64.5


def parse_address(formatted, default_state):
    m = ADDR_RE.search(formatted or "")
    if not m:
        return None, default_state, None, None
    street = (formatted or "")[: m.start()].strip(", ") or None
    return m["city"].strip(), m["state"].lower(), m["zip"], street


def build_record(row, feed, places, source_id):
    name = (row.get("name") or "").strip()
    fmt = FORMATS.get(row.get("attendance_option") or "in_person")
    if not name or fmt is None:  # inactive meetings are skipped
        return None
    try:
        day = DAYS[int(row["day"])]
    except (KeyError, ValueError, TypeError, IndexError):
        return None
    tm = TIME_RE.match((row.get("time") or "").strip())
    if not tm:
        return None
    entry = Flow(day=day, time=f"{int(tm[1]):02d}:{tm[2]}")
    em = TIME_RE.match((row.get("end_time") or "").strip())
    if em:
        dur = (int(em[1]) * 60 + int(em[2])) - (int(tm[1]) * 60 + int(tm[2]))
        if 0 < dur <= 480:
            entry["duration_min"] = dur

    city, st, zipc, street = parse_address(row.get("formatted_address"), feed["state"])
    if st not in places.by_state:
        return None

    rec = {
        "_state": st, "_place_slug": "online", "_name": name,
        "program": feed.get("program", "aa"),
        "categories": ["recovery-meeting"],
        "schedule": [entry],
        "format": fmt,
    }
    types = []
    for code in row.get("types") or []:
        token = slugify(str(code))
        if token and token not in types:
            types.append(token)
        if len(types) >= 8:
            break
    if types:
        rec["types"] = types

    if fmt != "online":
        geoid, place_slug = places.resolve(st, city or "")
        geo = None
        try:
            lat, lng = float(row["latitude"]), float(row["longitude"])
            if (lat, lng) != (0.0, 0.0):
                if not in_us_bounds(lat, lng):
                    return None
                geo = Flow(lat=round(lat, 5), lng=round(lng, 5))
        except (KeyError, TypeError, ValueError):
            pass
        if not geoid and geo:
            near = places.nearest(geo["lat"], geo["lng"])
            if near and near[0] == st:
                _, geoid, place_slug = near
        rec["_place_slug"] = place_slug
        venue_name = (row.get("location") or "").strip()
        if venue_name:
            rec["venue_name"] = venue_name
        if city and str(row.get("approximate", "no")).lower() != "yes":
            venue = {"street": street, "city": city, "state": st}
            if zipc:
                venue["zip"] = zipc
            rec["venue"] = Flow({k: v for k, v in venue.items() if v})
        if geoid:
            rec["place"] = geoid
        if geo:
            rec["geo"] = geo

    for field, key in (("url", "url"), ("conference_url", "conference_url")):
        value = (row.get(key) or "").strip()
        if URL_RE.match(value):
            rec[field] = value
    rec["external_ids"] = Flow(tsml=f"{feed['id']}:{row.get('id')}")
    rec["sources"] = [source_id]
    rec["verified"] = Flow(on=today(), method="api")
    return rec


def fetch_feed(feed, cache, force):
    """Fetch one feed, retrying once as a browser when a WAF turns us away.

    Intergroup sites run on WordPress behind filters that begin returning
    403/401 to non-browser clients without notice. Reading that as "no
    meetings" deletes a whole city's listings, so try the browser UA the
    project already keeps for such hosts before giving up. Still throttled,
    still identifies the project and a contact address.
    """
    ua = BROWSER_UA if feed.get("ua") == "browser" else UA
    try:
        return fetch(feed["feed"], cache, force=force, ua=ua)
    except SystemExit:
        if ua is BROWSER_UA:
            raise
        print(f"  {feed['id']}: refused the project UA — retrying as a browser")
        return fetch(feed["feed"], cache, force=force, ua=BROWSER_UA)


def existing_aa():
    """Every aa/ meeting record currently on disk."""
    base = DATA / "meetings"
    if not base.exists():
        return []
    return [rec for path in sorted(base.rglob("*.yaml"))
            for rec in load_yaml(path) or []
            if any(s.startswith("aa/") for s in rec.get("sources") or [])]


def carry_over(on_disk, skipped_feeds):
    """Keep the records of feeds that failed this run, exactly as they were.

    A fetch that fails is not evidence that a meeting stopped happening.
    Because the module owns the whole "aa/" prefix, letting a skipped feed fall
    out of `records` deletes its meetings outright — which is how eight
    intergroups' listings, some 8,000 meetings across Philadelphia, Atlanta,
    Portland and others, disappeared behind a warning nobody read. Carrying
    them keeps the old verified.on, so the staleness machinery reports them
    honestly until the feed answers again.
    """
    wanted = {f"aa/{fid}" for fid in skipped_feeds}
    carried = []
    for rec in on_disk:
        if not wanted & set(rec.get("sources") or []):
            continue
        rec = dict(rec)
        state, place_slug, _ = rec["id"].split("/", 2)
        rec["_state"], rec["_place_slug"] = state, place_slug
        rec["_name"] = rec.get("name", "")
        carried.append(rec)
    return carried


def main(argv):
    force = "--force" in argv
    places = Places()
    feeds = load_yaml(FEEDS)
    if not feeds:
        raise SystemExit(f"tsml: no feeds in {FEEDS}")

    records, seen_exact, skipped_feeds = [], set(), []
    for feed in feeds:
        cache = SOURCES / "tsml" / f"{feed['id']}.json"
        try:
            rows = json.loads(fetch_feed(feed, cache, force).read_text())
        except (SystemExit, json.JSONDecodeError) as e:
            print(f"WARNING: skipping feed {feed['id']}: {e}")
            skipped_feeds.append(feed["id"])
            continue
        if not isinstance(rows, list) or len(rows) < 20:
            print(f"WARNING: skipping feed {feed['id']}: not a plausible meeting list")
            skipped_feeds.append(feed["id"])
            if cache.exists():
                cache.unlink()  # don't cache a bad payload
            continue
        source_id = write_source(
            "aa", feed["id"],
            kind="api-feed", publisher=feed["name"],
            title=f"{feed['name']} meeting feed (TSML)",
            url=feed["url"], tier="primary",
        )
        kept = 0
        for row in rows:
            if not isinstance(row, dict):
                continue
            rec = build_record(row, feed, places, source_id)
            if rec is None:
                continue
            city, _, _, _ = parse_address(row.get("formatted_address"), feed["state"])
            exact = (rec["_name"].lower(), rec["schedule"][0]["day"],
                     rec["schedule"][0]["time"], rec["_state"], (city or "").lower())
            if exact in seen_exact:
                continue
            seen_exact.add(exact)
            records.append(rec)
            kept += 1
        print(f"{feed['id']}: {kept}/{len(rows)} kept")

    on_disk = existing_aa()
    if skipped_feeds:
        print(f"skipped feeds: {', '.join(skipped_feeds)}")
        carried = carry_over(on_disk, skipped_feeds)
        if carried:
            print(f"carried over {len(carried)} records from {len(skipped_feeds)} "
                  f"unreachable feed(s) rather than deleting them")
            records.extend(carried)

    # A feed answering with a short-but-plausible payload still slips past the
    # per-feed check; a large net loss across the whole family does not.
    if on_disk and len(records) < len(on_disk) * 0.8:
        raise SystemExit(
            f"tsml: {len(records)} records vs {len(on_disk)} on disk — a drop of "
            f"{100 * (1 - len(records) / len(on_disk)):.0f}%. Refusing to delete "
            f"the difference; investigate the feeds before re-running.")

    replace_records("meetings", "aa/", records)


if __name__ == "__main__":
    main(sys.argv[1:])
