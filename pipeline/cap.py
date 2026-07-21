"""Community Action Agencies (find-a-cap locator) -> org records (financial /
family-support).

communityactionpartnership.com/find-a-cap/ runs WP Store Locator; its public
admin-ajax store_search endpoint returns full agency JSON (name, street/city/
state/zip, lat/lng, phone, email, website, upstream id). The server validates
max_results / search_radius against the configured dropdown lists (best
accepted: 100 results, 500-mile radius) and the autoload dump caps at 100
stores, so the pull tiles the country: a coarse 250-mile grid over CONUS plus
fixed points for AK/HI and the territories, recursively subdividing any tile
that hits the 100-result cap. Tiles are deduped by upstream id; a WP REST
wpsl_stores id sweep (~960 published stores) cross-checks completeness.
Agencies are independent nonprofits/public bodies rather than chapters, so no
parent_org linkage is asserted; the national association gets its own record.
Facts-only re-expression, attributed (see DATA-RIGHTS.md: robots.txt allows
everything, and the site publishes no terms-of-use or privacy policy at all).

Usage: python3 -m pipeline.cap [--force]
"""
import html
import json
import re
import sys
from math import cos, radians

from .emit import Places, replace_records, today, write_source
from .util import Flow, SOURCES, fetch

AJAX = ("https://communityactionpartnership.com/wp-admin/admin-ajax.php"
        "?action=store_search&lat={lat:.4f}&lng={lng:.4f}"
        "&max_results=100&search_radius={radius}")
REST_IDS = ("https://communityactionpartnership.com/wp-json/wp/v2/wpsl_stores"
            "?per_page=100&page={n}&_fields=id")
PAGE_URL = "https://communityactionpartnership.com/find-a-cap/"

# radius -> (child radius, child grid step in degrees latitude) for tiles that
# hit the 100-result cap; each level re-queries a 3x3 grid over the parent
# tile's cell, with child circles that fully cover the child cells
SUBDIVIDE = {250: (100, 1.5), 100: (50, 0.6), 50: (25, 0.25)}

# fixed extra probes: AK, HI, PR/VI, GU/MP, AS
EXTRA_TILES = [
    (61.2, -149.9, 500), (64.8, -147.7, 500), (58.3, -134.4, 250),
    (60.8, -161.8, 250), (64.5, -165.4, 250), (71.3, -156.8, 250),
    (53.9, -166.5, 250), (55.3, -131.6, 250),
    (21.3, -157.9, 500),
    (18.35, -66.1, 250),
    (13.44, 144.79, 500),
    (-14.27, -170.70, 250),
]

STATES = {
    "al", "ak", "as", "az", "ar", "ca", "co", "ct", "de", "dc", "fl", "ga", "gu",
    "hi", "id", "il", "in", "ia", "ks", "ky", "la", "me", "md", "ma", "mi", "mn",
    "ms", "mo", "mt", "ne", "nv", "nh", "nj", "nm", "ny", "nc", "nd", "mp", "oh",
    "ok", "or", "pa", "pr", "ri", "sc", "sd", "tn", "tx", "ut", "vt", "vi", "va",
    "wa", "wv", "wi", "wy",
}

# a couple dozen rows carry full state names instead of postal codes
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

DESCRIPTION = ("Community Action Agency — local anti-poverty agency in the "
               "federal Community Services Block Grant network; programs "
               "commonly include utility and rent assistance, weatherization, "
               "and family services (offerings vary by agency).")


def norm_phone(raw: str) -> str | None:
    digits = re.sub(r"\D", "", raw or "")
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    if len(digits) == 10:
        return f"{digits[:3]}-{digits[3:6]}-{digits[6:]}"
    return None


def ensure_https(url: str) -> str:
    url = url.strip()
    return url if re.match(r"https?://", url, re.I) else f"https://{url}"


def tile(lat: float, lng: float, radius: int, force: bool) -> list[dict]:
    cache = SOURCES / "cap" / "tiles" / f"{lat:+07.2f}_{lng:+08.2f}_r{radius}.json"
    data = json.loads(fetch(AJAX.format(lat=lat, lng=lng, radius=radius),
                            cache, force=force).read_text())
    if not isinstance(data, list):
        if not data:  # a tile with no stores in range comes back as ""
            return []
        raise SystemExit(f"cap: store_search returned non-list at ({lat}, {lng})")
    return data


def collect(lat: float, lng: float, radius: int, stores: dict, force: bool):
    rows = tile(lat, lng, radius, force)
    for r in rows:
        stores[str(r.get("id"))] = r
    if len(rows) >= 100:  # nearest-100 cap hit: results beyond it are unseen
        if radius in SUBDIVIDE:
            child_radius, step = SUBDIVIDE[radius]
            step_lng = step / max(0.2, cos(radians(lat)))
            for i in (-1, 0, 1):
                for j in (-1, 0, 1):
                    collect(lat + i * step, lng + j * step_lng,
                            child_radius, stores, force)
        else:
            print(f"cap: tile ({lat}, {lng}) r{radius} still hits the "
                  f"100-result cap — possible coverage gap")


def rest_id_count(force: bool) -> int | None:
    """Published wpsl_stores count via WP REST, for a completeness cross-check.
    Auxiliary only: a failure is reported, not fatal."""
    try:
        ids, n = set(), 1
        while n <= 30:
            page = json.loads(fetch(REST_IDS.format(n=n),
                                    SOURCES / "cap" / f"rest-ids-p{n}.json",
                                    force=force).read_text())
            ids.update(p["id"] for p in page)
            if len(page) < 100:
                break
            n += 1
        return len(ids)
    except (SystemExit, Exception) as e:  # noqa: BLE001 — cross-check only
        print(f"cap: REST id sweep failed ({e}) — skipping completeness check")
        return None


def main(argv):
    force = "--force" in argv
    places = Places()

    stores: dict[str, dict] = {}
    lat = 25.0
    while lat < 50:
        step_lng = 4.5 / max(0.2, cos(radians(lat)))
        lng = -124.8
        while lng < -66.5:
            collect(lat, lng, 250, stores, force)
            lng += step_lng
        lat += 4.5
    for elat, elng, radius in EXTRA_TILES:
        collect(elat, elng, radius, stores, force)

    expected = rest_id_count(force)
    if expected is not None:
        print(f"cap: tiled pull found {len(stores)} stores; REST reports "
              f"{expected} published")
        if len(stores) < expected * 0.95:
            print(f"cap: tiles missed {expected - len(stores)} stores — "
                  f"consider a finer grid")

    source_id = write_source(
        "cap", "find-a-cap-locator",
        kind="api-feed", publisher="Community Action Partnership",
        title="Find a CAP agency locator (WP Store Locator store_search endpoint)",
        url=PAGE_URL, tier="primary",
    )

    records, skipped = [], 0
    for s in stores.values():
        name = " ".join(html.unescape(s.get("store") or "").split())
        state = (s.get("state") or "").strip().lower()
        state = state if state in STATES else STATE_NAMES.get(state, "")
        if not name or state not in STATES:
            skipped += 1
            continue
        rec = {
            "_state": state, "_place_slug": "", "_name": name,
            "categories": ["financial", "family-support"],
            "description": DESCRIPTION,
        }
        city = " ".join(html.unescape(s.get("city") or "").split())
        if city:
            addr = {"city": city, "state": state}
            street = ", ".join(
                " ".join(html.unescape(p).split())
                for p in (s.get("address"), s.get("address2")) if p and p.strip())
            if street:
                addr = {"street": street, **addr}
            zip_code = (s.get("zip") or "").strip()
            if re.fullmatch(r"\d{5}(-\d{4})?", zip_code):
                addr["zip"] = zip_code
            rec["address"] = Flow(addr)
            geoid, _ = places.resolve(state, city)
            if geoid:
                rec["place"] = geoid
        try:
            latf, lngf = float(s["lat"]), float(s["lng"])
            if -90 <= latf <= 90 and -180 <= lngf <= 180:
                rec["geo"] = Flow(lat=round(latf, 5), lng=round(lngf, 5))
        except (KeyError, TypeError, ValueError):
            pass
        phone = norm_phone(s.get("phone"))
        if phone:
            rec["phone"] = phone
        email = (s.get("email") or "").strip()
        if email:
            rec["email"] = email
        website = (s.get("url") or "").strip()
        if website:
            rec["website"] = ensure_https(website)
        if s.get("id"):
            rec["external_ids"] = Flow(wpsl=str(s["id"]))
        rec["sources"] = [source_id]
        rec["verified"] = Flow(on=today(), method="api")
        records.append(rec)
    if skipped:
        print(f"cap: skipped {skipped} stores without resolvable name/state")

    n_agencies = len(records)
    records.append({
        "_state": "us", "_place_slug": "",
        "_name": "Community Action Partnership",
        "id": "us/community-action-partnership",
        "categories": ["financial", "family-support"],
        "description": "National membership association of the roughly 1,000 "
                       "Community Action Agencies created under the Economic "
                       "Opportunity Act to fight poverty locally.",
        "website": "https://communityactionpartnership.com",
        "service_area": Flow(kind="national"),
        "sources": [source_id],
        "verified": Flow(on=today(), method="api"),
    })

    if n_agencies < 500:
        raise SystemExit(f"cap: only {n_agencies} agencies — expected ~960; aborting")
    replace_records("orgs", source_id, records)


if __name__ == "__main__":
    main(sys.argv[1:])
