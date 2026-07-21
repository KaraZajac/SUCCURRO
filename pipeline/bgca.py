"""Boys & Girls Clubs of America find-a-club -> site records (family-youth).

The bgca.org find-a-club page (WordPress + Google Maps) calls a BGCA-run App
Engine search API from the theme JS: GET
https://bgcaorg-find-a-c-1488560011850.appspot.com/x/v1/clubs/<lat>/<lng>/<miles>/
returns clubs inside a <miles>-half-width box around the point, capped at 25
per response regardless of box size. Replays cleanly with stdlib urllib.

Sweep geometry: probing a known club shows the capture region is a symmetric
box of +/- <miles> in latitude and cos-scaled longitude — but only at moderate
radii; at continent scale the response's own "box" field skews hundreds of
miles east and does not even bound the returned clubs, so it must never drive
recursion (v1 of this module did, and silently lost half the metros). Instead:
a fixed grid of 200-mile seed boxes covers CONUS/AK/HI/PR-VI, and any capped
(25-club) response splits into four self-computed quadrants at radius 0.55x
(10% overlap absorbs the small residual server skew). Every query caches under
sources/bgca/q/, so re-runs are cheap; SiteId dedupes the overlap.

Rights: ToS-checked 2026-07-21 — bgca.org publishes no website terms of use
(the privacy policy references one but only an SMS-terms page exists) and
robots.txt allows all agents on all paths. Facts-only re-expression of the
org's own locator feed, attributed.

Quirks: PhoneNumber uses "-" as a null sentinel; city names are randomly
upper/lowercased; many sites are school-hosted units whose SiteName is the
school. TRUE/FALSE program flags (teen center, summer, meals, weekends) are
kept as services: labels.

Usage: python3 -m pipeline.bgca [--force]
"""
import json
import math
import re
import sys

from .emit import Places, replace_records, today, write_source
from .util import Flow, SOURCES, fetch

API = "https://bgcaorg-find-a-c-1488560011850.appspot.com/x/v1/clubs"
FINDER = "https://www.bgca.org/get-involved/find-a-club/"
CACHE = SOURCES / "bgca" / "q"
CAP = 25          # server-side result cap per response
MIN_MILES = 2     # stop splitting below this half-width; warn if still capped

MILES_PER_DEG = 69.0
OVERLAP = 1.1     # children cover 0.55x half-width each -> 10% margin

# seed grids: (lat range, lng range, half-width miles); spacing 1.6x half-width
GRIDS = [
    ((24.0, 50.0), (-125.5, -66.5), 200),   # CONUS
    ((54.0, 71.5), (-168.5, -129.5), 300),  # Alaska
    ((18.7, 22.5), (-160.5, -154.5), 150),  # Hawaii
    ((17.5, 18.6), (-67.5, -64.2), 150),    # Puerto Rico + USVI
]


def seeds() -> list[tuple[float, float, float]]:
    out = []
    for (y0, y1), (x0, x1), m in GRIDS:
        step_lat = 1.6 * m / MILES_PER_DEG
        lat = y0 + step_lat / 2
        while lat < y1 + step_lat / 2:
            step_lng = 1.6 * m / (MILES_PER_DEG * math.cos(math.radians(lat)))
            lng = x0 + step_lng / 2
            while lng < x1 + step_lng / 2:
                out.append((round(lat, 4), round(lng, 4), m))
                lng += step_lng
            lat += step_lat
    return out

FLAG_SERVICES = [
    ("Teen_Center", "Teen center"),
    ("Summer", "Summer programs"),
    ("Meals", "Meals"),
    ("Weekends", "Open weekends"),
    ("Native", "Native services"),
    ("MPPP", "Military youth partnership"),
]

ZIP_RE = re.compile(r"\d{5}")


def query(lat: float, lng: float, miles: float, force: bool) -> dict:
    stem = f"{lat:.4f}_{lng:.4f}_{miles:g}".replace("-", "m").replace(".", "_")
    path = fetch(f"{API}/{lat:.4f}/{lng:.4f}/{miles:g}/", CACHE / f"{stem}.json",
                 force=force)
    data = json.loads(path.read_bytes())
    if data.get("status") != "SUCCESS" or "clubs" not in data:
        raise SystemExit(f"bgca: bad API response for {lat},{lng},{miles}: "
                         f"{str(data)[:200]}")
    return data


def sweep(force: bool) -> dict[str, dict]:
    """Grid + quadtree over the seed boxes; returns clubs by SiteId. Children
    are computed from the *request* geometry, never the response box (which is
    unreliable — see module docstring)."""
    clubs: dict[str, dict] = {}
    stack = seeds()
    n_queries = capped_leaves = 0
    while stack:
        lat, lng, miles = stack.pop()
        data = query(lat, lng, miles, force)
        n_queries += 1
        for club in data["clubs"]:
            sid = str(club.get("SiteId") or "")
            if sid:
                clubs.setdefault(sid, club)
        if len(data["clubs"]) >= CAP:
            if miles / 2 < MIN_MILES:
                capped_leaves += 1  # accept the 25; sibling overlap covers strays
                continue
            dlat = miles / 2 / MILES_PER_DEG
            dlng = miles / 2 / (MILES_PER_DEG * math.cos(math.radians(lat)))
            for cy in (lat - dlat, lat + dlat):
                for cx in (lng - dlng, lng + dlng):
                    stack.append((round(cy, 4), round(cx, 4),
                                  round(miles / 2 * OVERLAP, 4)))
    print(f"sweep: {n_queries} box queries -> {len(clubs)} unique sites"
          + (f" ({capped_leaves} still-capped <{MIN_MILES}mi leaves)"
             if capped_leaves else ""))
    return clubs


def fix_case(name: str) -> str:
    name = name.strip()
    return name.title() if name.isupper() or name.islower() else name


def norm_phone(raw: str) -> str | None:
    digits = re.sub(r"\D", "", raw or "")
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    if len(digits) == 10:
        return f"{digits[:3]}-{digits[3:6]}-{digits[6:]}"
    return None


def main(argv):
    force = "--force" in argv
    places = Places()
    source_id = write_source(
        "bgca", "find-a-club",
        kind="api-feed", publisher="Boys & Girls Clubs of America",
        title="BGCA find-a-club search API",
        url=FINDER, tier="primary",
    )

    clubs = sweep(force)
    records, seen = [], set()
    skipped_status = skipped_state = skipped_country = 0
    statuses: dict[str, int] = {}
    for club in clubs.values():
        status = (club.get("SiteStatusName") or "").strip()
        statuses[status] = statuses.get(status, 0) + 1
        if not status.startswith("Active"):
            skipped_status += 1
            continue
        if (club.get("Country") or "US").strip().upper() not in ("US", "USA", ""):
            skipped_country += 1
            continue
        name = (club.get("SiteName") or "").strip()
        if not name:
            continue
        st = (club.get("State") or "").strip().lower()
        if st not in places.by_state:
            skipped_state += 1
            continue
        city = fix_case(club.get("City") or "")
        street = " ".join(
            p.strip() for p in (club.get(f"Address{i}") for i in range(1, 5))
            if p and p.strip())
        key = (name.lower(), street.lower(), city.lower())
        if key in seen:
            continue
        seen.add(key)

        geoid, place_slug = places.resolve(st, city)
        rec = {
            "_state": st, "_place_slug": place_slug, "_name": name,
            "categories": ["family-youth"],
            "description": "Boys & Girls Club",
        }
        addr = {}
        if street:
            addr["street"] = street
        if city:
            addr["city"] = city
            addr["state"] = st
            zip_code = (club.get("ZipCode1") or "").strip()
            if ZIP_RE.fullmatch(zip_code):
                addr["zip"] = zip_code
            rec["address"] = Flow(addr)
        try:
            lat, lng = float(club["lat"]), float(club["lng"])
            if 15 <= lat <= 72 and -180 <= lng <= -60:
                rec["geo"] = Flow(lat=round(lat, 5), lng=round(lng, 5))
        except (KeyError, TypeError, ValueError):
            pass
        if not geoid and "geo" in rec:
            near = places.nearest(rec["geo"]["lat"], rec["geo"]["lng"])
            if near and near[0] == st:  # state-matched nearest fallback
                geoid = near[1]
        if geoid:
            rec["place"] = geoid
        phone = norm_phone(club.get("PhoneNumber"))
        if phone:
            rec["phone"] = phone
        website = (club.get("WebsiteAddress") or "").strip()
        if re.match(r"https?://", website, re.I):
            rec["website"] = website
        elif re.match(r"^[A-Za-z0-9-]+(\.[A-Za-z0-9-]+)+", website):
            rec["website"] = f"http://{website}"
        services = [label for flag, label in FLAG_SERVICES
                    if (club.get(flag) or "").upper() == "TRUE"]
        if services:
            rec["services"] = services
        ext = {"bgca_site": str(club["SiteId"])}
        if club.get("OrganizationGlobalId") not in (None, "", "0"):
            ext["bgca_org"] = str(club["OrganizationGlobalId"])
        rec["external_ids"] = Flow(ext)
        rec["sources"] = [source_id]
        rec["verified"] = Flow(on=today(), method="api")
        records.append(rec)

    print(f"kept {len(records)} club sites "
          f"(skipped: {skipped_status} non-active, {skipped_state} outside "
          f"place registry, {skipped_country} non-US); statuses: {statuses}")
    if len(records) < 3000:
        raise SystemExit(f"bgca: only {len(records)} club sites — expected "
                         "4,000+; aborting")

    replace_records("sites", source_id, records)


if __name__ == "__main__":
    main(sys.argv[1:])
