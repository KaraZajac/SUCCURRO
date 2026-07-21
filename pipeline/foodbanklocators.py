"""Feeding America member food-bank pantry/agency locators -> site records.

Harvests every bank in pipeline/curated/foodbank-locators.yaml (the registry
built from docs/research/foodbank-locators-2026-07.md): one parser per locator
platform family (wpsl, wpgmza, asl, slp, storepoint, storerocket, mymaps KML,
arcgis, ssf, foodfinder, mapsvg, slw, freshtrak, tribevenues) plus small
per-bank custom parsers for the static-HTML and inline-JSON sites. Page-capped
WP Store Locator plugins are un-capped with a lat/lng grid sweep (registry
`sweep`); Store Locator Plus honors an options[initial_results_returned]
override. The 2026-07 headless pass added endpoints first discovered with a
one-shot chromium XHR capture; all of them replay with plain urllib (POST /
cookie flows go through cache_json), so no browser is needed at runtime.

Records are pantry/agency sites: facts only (name, address, phone, hours where
structured, geo), org FK set to the bank (they're the bank's partner agencies),
categories food-pantry by default, meal-program where the source's type says
soup kitchen/meal site, food-bank for the bank's own distribution centers.
Neighboring banks list overlapping agencies - exact (name, street, city) dedupe
within and across banks handles that.

Ownership: each bank gets a source record foodbank/<registry-id>; the module
owns everything citing the "foodbank/" prefix, so banks later dropped from the
registry are cleaned up on the next run. A broken bank is skipped loudly; the
run aborts if fewer than 45 banks or 6,000 records survive.

Usage: python3 -m pipeline.foodbanklocators [--force] [--dry bank-id ...]
"""
import csv
import html as htmllib
import io
import json
import re
import sys
import time
import urllib.parse
import urllib.request

from .emit import Places, norm, replace_records, today, write_source
from .util import BROWSER_UA, Flow, ROOT, SOURCES, UA, fetch, load_yaml

REGISTRY = ROOT / "pipeline" / "curated" / "foodbank-locators.yaml"
CACHE = SOURCES / "foodbanklocators"

STATES = {
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
STATE_CODES = set(STATES.values())

DAY_TOKENS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
DAY_NAMES = {"monday": "mon", "tuesday": "tue", "wednesday": "wed",
             "thursday": "thu", "friday": "fri", "saturday": "sat",
             "sunday": "sun"}

_DIGITS = re.compile(r"\d")
ZIP_RE = re.compile(r"^(\d{5})(?:-\d{4})?$")
# one-line address: "203 South Monroe Street, Columbia, KY[ 42728][, USA]"
ONELINE_COMMA = re.compile(
    r"^(?P<street>.+?),\s*(?P<city>[^,]+?),?\s+(?P<state>[A-Za-z]{2})\.?"
    r"(?:\s+(?P<zip>\d{5})(?:-\d{4})?)?\s*$")
# "2021 W Main Street Albert Lea MN 56007" (no commas) - tail is "ST zip",
# street/city boundary is the last street-suffix word
ONELINE_SPACE = re.compile(
    r"^(?P<head>.+?)\s+(?P<state>[A-Z]{2})\.?\s+(?P<zip>\d{5})(?:-\d{4})?\s*$")
STREET_SUFFIX = {
    "st", "street", "ave", "avenue", "rd", "road", "dr", "drive", "blvd",
    "boulevard", "hwy", "highway", "ln", "lane", "way", "ct", "court", "pkwy",
    "parkway", "cir", "circle", "plaza", "sq", "square", "ter", "terrace",
    "loop", "pl", "place", "trail", "trl", "pike", "expy", "expressway",
    "broadway"}


def clean(value) -> str:
    if value is None:
        return ""
    return " ".join(str(value).replace("\xa0", " ").split())


def strip_tags(fragment: str) -> str:
    return clean(htmllib.unescape(re.sub(r"<[^>]+>", " ", fragment or "")))


def clean_phone(raw) -> str | None:
    digits = "".join(_DIGITS.findall(str(raw or "")))
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    if len(digits) == 10:
        return f"{digits[:3]}-{digits[3:6]}-{digits[6:]}"
    return None


def clean_zip(raw) -> str | None:
    s = clean(raw)
    if s.endswith(".0"):
        s = s[:-2]
    m = ZIP_RE.match(s)
    return m.group(1) if m else None


def state_code(raw, default=None) -> str | None:
    s = clean(raw).lower().strip(".")
    if s in STATE_CODES:
        return s
    return STATES.get(s, default)


def in_us_bounds(lat, lng) -> bool:
    return 17.5 <= lat <= 71.5 and -180.0 <= lng <= -64.5


def to_geo(lat, lng):
    try:
        lat, lng = float(lat), float(lng)
    except (TypeError, ValueError):
        return None
    if (lat, lng) == (0.0, 0.0) or not in_us_bounds(lat, lng):
        return None
    return Flow(lat=round(lat, 5), lng=round(lng, 5))


def parse_oneline(addr: str, default_state=None):
    """One-line US address -> (street, city, state, zip); unparsed input
    comes back as (addr, None, default_state, None)."""
    addr = clean(htmllib.unescape(addr or ""))
    addr = re.sub(r",?\s*(USA|United States)\.?$", "", addr, flags=re.I).strip(" ,")
    if not addr:
        return None, None, default_state, None
    m = ONELINE_COMMA.match(addr)
    if m and state_code(m["state"]):
        return (m["street"].strip(" ,") or None, m["city"].strip(" ,"),
                state_code(m["state"]), m["zip"])
    m = ONELINE_SPACE.match(addr)
    if m and state_code(m["state"]):
        words = m["head"].split()
        cut = max((i for i, w in enumerate(words)
                   if w.rstrip(".,").lower() in STREET_SUFFIX), default=None)
        if cut is not None and 1 <= len(words) - cut - 1 <= 3:
            return (" ".join(words[:cut + 1]).strip(" ,"),
                    " ".join(words[cut + 1:]).strip(" ,."),
                    state_code(m["state"]), m["zip"])
        if len(words) >= 2:  # no suffix found: assume a one-word city
            return (" ".join(words[:-1]).strip(" ,"), words[-1].strip(" ,."),
                    state_code(m["state"]), m["zip"])
    return addr, None, default_state, None


# --- hours ------------------------------------------------------------------

TIME12 = re.compile(r"^(\d{1,2})(?::(\d{2}))?\s*(am|pm|a\.?m\.?|p\.?m\.?)?$", re.I)
WINDOW = re.compile(r"^(.*?)\s*(?:-|–|—|to)\s*(.*)$")


def _to24(text, meridiem_hint=None):
    m = TIME12.match(clean(text))
    if not m:
        return None
    hour, minute = int(m.group(1)), int(m.group(2) or 0)
    mer = (m.group(3) or meridiem_hint or "").lower().replace(".", "")
    if not mer or hour > 12 or minute > 59:
        return None
    if mer == "pm" and hour != 12:
        hour += 12
    if mer == "am" and hour == 12:
        hour = 0
    return f"{hour:02d}:{minute:02d}"


def parse_window(text):
    """'9:00 AM - 5:00 PM' / '3PM-7PM' / '10:00-23:30' -> (open, close)."""
    text = clean(text)
    m = re.match(r"^([01]?\d|2[0-3]):([0-5]\d)\s*-\s*([01]?\d|2[0-3]):([0-5]\d)$", text)
    if m:  # already 24h
        return (f"{int(m.group(1)):02d}:{m.group(2)}",
                f"{int(m.group(3)):02d}:{m.group(4)}")
    m = WINDOW.match(text)
    if not m:
        return None
    close_m = TIME12.match(clean(m.group(2)))
    hint = close_m.group(3) if close_m else None
    open_t, close_t = _to24(m.group(1), hint), _to24(m.group(2))
    if not open_t or not close_t:
        return None
    if open_t >= close_t:  # '9:00 - 1:00 PM' style: opening was really AM
        alt = _to24(m.group(1), "am")
        if alt and alt < close_t:
            open_t = alt
        else:
            return None
    return open_t, close_t


def hours_from_pairs(pairs):
    """[(day_token, window_text), ...] -> hours entries, same-window days
    merged. Unparseable windows are dropped (never guessed)."""
    by_window: dict[tuple, list] = {}
    for day, text in pairs:
        if day not in DAY_TOKENS or not clean(text):
            continue
        if re.search(r"closed", text, re.I):
            continue
        w = parse_window(text)
        if w and day not in by_window.setdefault(w, []):
            by_window[w].append(day)
    entries = [
        Flow(days=sorted(days, key=DAY_TOKENS.index), open=w[0], close=w[1])
        for w, days in by_window.items()]
    return sorted(entries, key=lambda e: (DAY_TOKENS.index(e["days"][0]), e["open"])) or None


# --- classification -----------------------------------------------------------

MEAL_RE = re.compile(
    r"soup kitchen|meal site|meal program|hot meal|free meal|community meal|"
    r"congregate meal|community kitchen|meals?\b(?!s? ?on wheels)", re.I)
DIST_RE = re.compile(r"distribution center|warehouse", re.I)


def classify(bank, name: str, type_text: str) -> list[str]:
    """Category tokens: food-pantry default; meal-program when the record's
    published type says meals; food-bank for the bank's own centers."""
    if DIST_RE.search(f"{name} {type_text}") or norm(name).startswith(norm(bank["name"])):
        return ["food-bank"]
    if MEAL_RE.search(type_text) or re.search(r"soup kitchen|community kitchen", name, re.I):
        return ["meal-program"]
    return ["food-pantry"]


# --- shared fetch helpers -------------------------------------------------------

def fetch_json(bank, url, cachefile, force):
    ua = BROWSER_UA if bank.get("ua") == "browser" else UA
    return json.loads(fetch(url, CACHE / bank["id"] / cachefile, force=force,
                            ua=ua).read_text(errors="replace"))


def fetch_text(bank, url, cachefile, force):
    ua = BROWSER_UA if bank.get("ua") == "browser" else UA
    return fetch(url, CACHE / bank["id"] / cachefile, force=force,
                 ua=ua).read_text(errors="replace")


def cache_json(bank, cachefile, force, producer):
    """Cache-through for endpoints util.fetch can't express (POST, cookie
    flows): producer() -> bytes, called only on a cache miss."""
    path = CACHE / bank["id"] / cachefile
    if force or not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(producer())
        print(f"fetched -> {path.relative_to(ROOT)}")
    return json.loads(path.read_text(errors="replace"))


def post_bytes(url, data, headers=None, timeout=120):
    """Throttled POST (the shared util helper is GET-only)."""
    time.sleep(1.0)
    h = {"User-Agent": BROWSER_UA}
    h.update(headers or {})
    with urllib.request.urlopen(
            urllib.request.Request(url, data=data, headers=h), timeout=timeout) as resp:
        return resp.read()


def frange(lo, hi, step):
    v = lo
    while v <= hi + 1e-9:
        yield round(v, 4)
        v += step


def row(name, *, street=None, street2=None, city=None, state=None, zip5=None,
        phone=None, email=None, website=None, lat=None, lng=None, hours=None,
        type_text="", uid=None):
    return {"name": clean(htmllib.unescape(str(name or ""))), "street": street,
            "street2": street2, "city": city, "state": state, "zip": zip5,
            "phone": phone, "email": email, "website": website, "lat": lat,
            "lng": lng, "hours": hours, "type": type_text, "uid": uid}


# --- platform: WP Store Locator (wpsl) --------------------------------------------

def wpsl_hours(html_table):
    pairs = []
    for day, cell in re.findall(r"<tr><td>([A-Za-z]+)</td><td>(.*?)</td></tr>",
                                html_table or ""):
        token = DAY_NAMES.get(day.lower())
        if token:
            pairs.append((token, strip_tags(cell)))
    return hours_from_pairs(pairs)


def wpsl_rows(bank, data):
    rows = []
    for r in data:
        if not isinstance(r, dict) or not clean(r.get("store")):
            continue
        rows.append(row(
            r["store"], street=clean(r.get("address")) or None,
            street2=clean(r.get("address2")) or None,
            city=clean(r.get("city")) or None,
            state=state_code(r.get("state"), bank["state"]),
            zip5=clean_zip(r.get("zip")), phone=clean_phone(r.get("phone")),
            email=clean(r.get("email")) or None,
            website=clean(r.get("url")) or None, lat=r.get("lat"),
            lng=r.get("lng"), hours=wpsl_hours(r.get("hours")),
            uid=r.get("id")))
    return rows


def harvest_wpsl(bank, force):
    if "sweep" not in bank:
        url = f"{bank['endpoint']}?action=store_search&autoload=1"
        return wpsl_rows(bank, fetch_json(bank, url, "dump.json", force))
    sweeps = bank["sweep"]
    if isinstance(sweeps, dict):
        sweeps = [sweeps]
    seen, rows = set(), []
    for bi, sw in enumerate(sweeps):
        la0, la1, lo0, lo1 = sw["box"]
        points = [(la, lo) for la in frange(la0, la1, sw["step"])
                  for lo in frange(lo0, lo1, sw["step"])]
        for i, (la, lo) in enumerate(points):
            url = (f"{bank['endpoint']}?action=store_search&lat={la}&lng={lo}"
                   f"&max_results={sw['max_results']}&search_radius={sw['radius']}")
            data = fetch_json(bank, url, f"sweep-{bi}-{i:03d}.json", force)
            for r in wpsl_rows(bank, data if isinstance(data, list) else []):
                if r["uid"] not in seen:
                    seen.add(r["uid"])
                    rows.append(r)
    return rows


# --- platform: WP Go Maps (wpgmza) -------------------------------------------------

def harvest_wpgmza(bank, force):
    rows = []
    for r in fetch_json(bank, bank["endpoint"], "dump.json", force):
        name = clean(htmllib.unescape(r.get("title") or ""))
        if not name:
            continue  # nameless markers are decorations, not agencies
        street, city, st, zip5 = parse_oneline(r.get("address"), bank["state"])
        rows.append(row(name, street=street, city=city, state=st, zip5=zip5,
                        website=clean(r.get("link")) or None, lat=r.get("lat"),
                        lng=r.get("lng"), uid=r.get("id")))
    return rows


# --- platform: Agile Store Locator (asl) --------------------------------------------

def asl_hours(raw):
    try:
        data = json.loads(raw or "")
    except (TypeError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    pairs = []
    for day, val in data.items():
        vals = val if isinstance(val, list) else [val]
        for v in vals:
            if isinstance(v, str) and v not in ("0", "1"):
                pairs.append((day[:3].lower(), v))
    return hours_from_pairs(pairs)


def harvest_asl(bank, force):
    url = f"{bank['endpoint']}?action=asl_load_stores&load_all=1&layout=1"
    rows = []
    for r in fetch_json(bank, url, "dump.json", force):
        if not clean(r.get("title")):
            continue
        rows.append(row(
            r["title"], street=clean(r.get("street")) or None,
            city=clean(r.get("city")) or None,
            state=state_code(r.get("state"), bank["state"]),
            zip5=clean_zip(r.get("postal_code")),
            phone=clean_phone(r.get("phone")),
            email=clean(r.get("email")) or None,
            website=clean(r.get("website")) or None, lat=r.get("lat"),
            lng=r.get("lng"), hours=asl_hours(r.get("open_hours")),
            uid=r.get("id")))
    return rows


# --- platform: Store Locator Plus (slp) ----------------------------------------------

def harvest_slp(bank, force):
    lat, lng = bank["center"]
    url = (f"{bank['endpoint']}?action=csl_ajax_onload&lat={lat}&lng={lng}"
           "&radius=10000&options%5Binitial_results_returned%5D=3000")
    data = fetch_json(bank, url, "dump.json", force)
    rows = []
    for r in data.get("response") or []:
        name = strip_tags(r.get("name") or "")
        if not name:
            continue
        rows.append(row(
            name, street=strip_tags(r.get("address")) or None,
            street2=strip_tags(r.get("address2")) or None,
            city=clean(r.get("city")) or None,
            state=state_code(r.get("state"), bank["state"]),
            zip5=clean_zip(r.get("zip")), phone=clean_phone(r.get("phone")),
            email=clean(r.get("email")) or None,
            website=clean(r.get("url")) or None, lat=r.get("lat"),
            lng=r.get("lng"), type_text=clean(r.get("category_names")),
            uid=r.get("id")))
    return rows


# --- platform: Storepoint --------------------------------------------------------------

def harvest_storepoint(bank, force):
    data = fetch_json(bank, bank["endpoint"], "dump.json", force)
    rows = []
    for r in data["results"]["locations"]:
        name = clean(r.get("name"))
        name = re.sub(r"^\d{1,2}/\d{1,2}\s+", "", name)  # date-stamped mobiles
        if not name:
            continue
        street, city, st, zip5 = parse_oneline(r.get("streetaddress"), bank["state"])
        pairs = [(d[:3], r.get(d)) for d in DAY_NAMES]
        rows.append(row(
            name, street=street, city=city, state=st, zip5=zip5,
            phone=clean_phone(r.get("phone")),
            email=clean(r.get("email")) or None,
            website=clean(r.get("website")) or None, lat=r.get("loc_lat"),
            lng=r.get("loc_long"), hours=hours_from_pairs(pairs),
            type_text=clean(r.get("tags")), uid=r.get("id")))
    return rows


# --- platform: StoreRocket ---------------------------------------------------------------

def harvest_storerocket(bank, force):
    data = fetch_json(bank, bank["endpoint"], "dump.json", force)
    rows = []
    for r in data["results"]["locations"]:
        if not clean(r.get("name")):
            continue
        pairs = [(d, v) for d, v in (r.get("hours") or {}).items()
                 if isinstance(v, str)]
        rows.append(row(
            r["name"], street=clean(r.get("address_line_1")) or None,
            street2=clean(r.get("address_line_2")) or None,
            city=clean(r.get("city")) or None,
            state=state_code(r.get("state"), bank["state"]),
            zip5=clean_zip(r.get("postcode")),
            phone=clean_phone(r.get("phone")),
            website=clean(r.get("url")) or None, lat=r.get("lat"),
            lng=r.get("lng"), hours=hours_from_pairs(pairs),
            type_text=clean(r.get("location_type_name")), uid=r.get("id")))
    return rows


# --- platform: Google My Maps (KML) ----------------------------------------------------------

KML_COORD = re.compile(r"<coordinates>\s*(-?[\d.]+),(-?[\d.]+)")


def kml_value(block, tag):
    m = re.search(rf"<{tag}>(.*?)</{tag}>", block, re.S)
    if not m:
        return ""
    return strip_tags(re.sub(r"<!\[CDATA\[|\]\]>", "", m.group(1)))


def harvest_mymaps(bank, force):
    text = fetch_text(bank, bank["endpoint"], "dump.kml", force)
    rows = []
    folder = ""
    for kind, block in re.findall(
            r"<Folder>\s*<name>(.*?)</name>|<Placemark>(.*?)</Placemark>", text, re.S):
        if kind or not block:
            folder = strip_tags(re.sub(r"<!\[CDATA\[|\]\]>", "", kind))
            continue
        if re.search(r"outside service area", folder, re.I):
            continue  # neighboring banks' territory, not this bank's network
        name = kml_value(block, "name")
        if not name:
            continue
        cm = KML_COORD.search(block)
        addr = kml_value(block, "address")
        if not addr:
            m = re.search(r'<Data name="Distribution Address">\s*<value>(.*?)</value>',
                          block, re.S)
            addr = strip_tags(m.group(1)) if m else ""
        street, city, st, zip5 = parse_oneline(addr, None)
        if street and not city:  # "99-005 Moanalua Rd. Aiea, HI 96701" pattern
            m = re.match(r"^(.*?[a-z.])\s+([A-Z][A-Za-z .'-]+),\s*([A-Z]{2})\s*(\d{5})?",
                         addr)
            if m:
                street, city, st, zip5 = (m.group(1), m.group(2),
                                          state_code(m.group(3)), m.group(4))
        rows.append(row(
            name, street=street, city=city, state=st or bank["state"], zip5=zip5,
            phone=clean_phone(kml_value(block, "description")),
            lat=cm.group(2) if cm else None, lng=cm.group(1) if cm else None,
            type_text=folder))
    return rows


# --- platform: ArcGIS FeatureServer ------------------------------------------------------------

def harvest_arcgis(bank, force):
    features, offset, page = [], 0, 1
    while True:
        url = (f"{bank['endpoint']}/query?where=1%3D1&outFields=*&f=json"
               f"&outSR=4326&orderByFields={bank['oid']}"
               f"&resultRecordCount=1000&resultOffset={offset}")
        data = fetch_json(bank, url, f"p{page}.json", force)
        if "features" not in data:
            raise SystemExit(f"unexpected arcgis payload: {str(data)[:200]}")
        features.extend(data["features"])
        if not data.get("exceededTransferLimit") and len(data["features"]) < 1000:
            break
        offset += len(data["features"])
        page += 1
    fmap = bank["fields"]
    rows = []
    for feat in features:
        a = feat["attributes"]
        f = {k: clean(a.get(v)) for k, v in fmap.items()}
        if not f.get("name"):
            continue
        street, city, st, zip5 = (f.get("street") or None, f.get("city") or None,
                                  None, clean_zip(f.get("zip")))
        if f.get("address"):
            street, city, st, zip5 = parse_oneline(f["address"], None)
        if bank.get("state_field"):
            st = state_code(a.get(bank["state_field"]), st)
        geom = feat.get("geometry") or {}
        rows.append(row(
            f["name"], street=street, street2=f.get("street2") or None,
            city=city, state=st or bank["state"], zip5=zip5,
            phone=clean_phone(f.get("phone")), email=f.get("email") or None,
            website=f.get("website") or None, lat=geom.get("y"),
            lng=geom.get("x"), type_text=f.get("type", ""),
            uid=a.get(bank["oid"])))
    return rows


# --- platform: Super Store Finder (XML) ----------------------------------------------------------

def harvest_ssf(bank, force):
    text = fetch_text(bank, bank["endpoint"], "dump.xml", force)
    rows = []
    for item in re.findall(r"<item>(.*?)</item>", text, re.S):
        name = kml_value(item, "location")
        if not name:
            continue
        addr = kml_value(item, "address")
        street, city, st, zip5 = parse_oneline(addr, None)
        if not city:  # "3253 E. Shields Ave.  Fresno,  California 93726"
            parts = re.split(r"\s{2,}", addr.strip())
            m = re.match(r"^([A-Za-z .'-]+?),?\s*$", parts[1]) if len(parts) >= 3 else None
            if m:
                street = parts[0].rstrip(",")
                city = m.group(1).strip(" ,")
                tail = re.match(r"([A-Za-z ]+?)\.?\s+(\d{5})?", parts[2])
                if tail:
                    st, zip5 = state_code(tail.group(1)), tail.group(2)
        rows.append(row(
            name, street=street, city=city, state=st or bank["state"], zip5=zip5,
            phone=clean_phone(kml_value(item, "telephone")),
            email=kml_value(item, "email") or None,
            website=kml_value(item, "website") or None,
            lat=kml_value(item, "latitude"), lng=kml_value(item, "longitude")))
    return rows


# --- platform: food-finder app (data-props inline JSON) --------------------------------------------

FF_DAYS = ("sun", "mon", "tue", "wed", "thu", "fri", "sat")  # 0 = Sunday


def foodfinder_hours(groups):
    entries = []
    for g in groups or []:
        days = [FF_DAYS[d] for d in g.get("days") or [] if 0 <= d <= 6]
        open_t = (g.get("open_time") or "")[-5:]
        close_t = (g.get("close_time") or "")[-5:]
        if not days or not re.match(r"^\d{2}:\d{2}$", open_t) \
                or not re.match(r"^\d{2}:\d{2}$", close_t):
            continue
        entry = Flow(days=sorted(set(days), key=FF_DAYS.index),
                     open=open_t, close=close_t)
        note = clean((g.get("comment") or {}).get("en") or "")
        if 0 < len(note) <= 80:
            entry["note"] = note
        entries.append(entry)
    return entries or None


def harvest_foodfinder(bank, force):
    page = fetch_text(bank, bank["endpoint"], "page.html", force)
    m = re.search(r'data-props="([^"]*)"', page)
    if not m:
        raise SystemExit("no data-props JSON on page - layout changed")
    data = json.loads(htmllib.unescape(m.group(1)))
    rows = []
    for r in data["allLocations"]:
        name = clean(r.get("name"))
        if not name:
            continue
        lines = [clean(x) for x in (r.get("address") or "").split("\n") if clean(x)]
        street = ", ".join(lines[:-1]) or None
        city = st = zip5 = None
        if lines:
            lm = re.match(r"^(.+?),\s*([A-Z]{2})\s*(\d{5})?", lines[-1])
            if lm:
                city, st, zip5 = lm.group(1), state_code(lm.group(2)), lm.group(3)
            else:
                street = ", ".join(lines) or None
        cats = []
        for c in r.get("location_categories") or []:
            label = c.get("label") if isinstance(c, dict) else None
            label = label.get("en") if isinstance(label, dict) else label
            if label:
                cats.append(label)
        website = next((w for w in (r.get("website") or [])
                        if isinstance(w, str) and w.startswith("http")), None)
        rows.append(row(
            name, street=street, city=city, state=st or bank["state"], zip5=zip5,
            phone=clean_phone(r.get("phone")), website=website,
            lat=r.get("latitude"), lng=r.get("longitude"),
            hours=foodfinder_hours(r.get("grouped_location_hours")),
            type_text=", ".join(cats), uid=r.get("id")))
    return rows


# --- platform: MapSVG (WP REST objects dump) ------------------------------------------------------

def harvest_mapsvg(bank, force):
    data = fetch_json(bank, bank["endpoint"], "dump.json", force)
    rows = []
    for r in data["items"]:
        name = clean(r.get("name") or r.get("title"))
        if not name:
            continue
        rows.append(row(
            name, street=(clean(r.get("address")).split(",")[0] or None),
            city=clean(r.get("city")) or None,
            state=state_code(r.get("state"), bank["state"]),
            zip5=clean_zip(r.get("zip")), phone=clean_phone(r.get("phone")),
            lat=r.get("latitude"), lng=r.get("longitude"),
            type_text=clean(r.get("services")), uid=r.get("id")))
    return rows


# --- platform: Store Locator Widgets (cdn JSONP dump) ---------------------------------------------

def harvest_slw(bank, force):
    text = fetch_text(bank, bank["endpoint"], "dump.jsonp", force)
    data = json.loads(re.sub(r"^\s*slw\(|\)\s*$", "", text.strip()))
    rows = []
    for r in data.get("stores") or []:
        name = clean(r.get("name"))
        if not name:
            continue
        d = r.get("data") or {}
        addr = clean(d.get("address"))
        street, city, st, zip5 = parse_oneline(addr, None)
        if not city:  # "18510 Madison Avenue, FL, 32820" (no city published)
            m = re.match(r"^(.*?),\s*([A-Z]{2}),?\s*(\d{5})?$", addr)
            if m:
                street, city, st, zip5 = m.group(1).strip(" ,"), None, \
                    state_code(m.group(2)), m.group(3)
        rows.append(row(
            name, street=street or None, city=city,
            state=st or bank["state"], zip5=zip5,
            phone=clean_phone(d.get("phone")),
            website=clean(d.get("website")) or None, lat=d.get("map_lat"),
            lng=d.get("map_lng"), uid=r.get("storeid")))
    return rows


# --- platform: FreshTrak / PantryTrak pantry-finder API -------------------------------------------

def harvest_freshtrak(bank, force):
    prefixes = tuple(bank.get("zip_prefixes") or ())
    seen, rows = set(), []
    for zc in bank["zips"]:
        url = f"{bank['endpoint']}?zip_code={zc}&distance={bank['distance']}"
        data = fetch_json(bank, url, f"zip-{zc}.json", force)
        for r in data.get("agencies") or []:
            if r.get("id") in seen or not clean(r.get("name")):
                continue
            zip5 = clean_zip(r.get("zip"))
            if prefixes and not (zip5 or "").startswith(prefixes):
                continue  # another bank's territory (the API is bank-agnostic)
            seen.add(r.get("id"))
            types = ", ".join(sorted({clean(e.get("name")) for e in r.get("events") or []
                                      if clean(e.get("name"))}))
            rows.append(row(
                r["name"], street=clean(r.get("address")) or None,
                city=clean(r.get("city")) or None,
                state=state_code(r.get("state"), bank["state"]), zip5=zip5,
                phone=clean_phone(r.get("phone")), lat=r.get("latitude"),
                lng=r.get("longitude"), type_text=types, uid=r.get("id")))
    return rows


# --- platform: The Events Calendar venues REST ----------------------------------------------------

def harvest_tribevenues(bank, force):
    rows, page = [], 1
    while True:
        data = fetch_json(bank, f"{bank['endpoint']}?per_page=50&page={page}",
                          f"venues-p{page}.json", force)
        for v in data.get("venues") or []:
            name = strip_tags(v.get("venue") or "")
            if not name:
                continue
            rows.append(row(
                name, street=clean(v.get("address")) or None,
                city=clean(v.get("city")) or None,
                state=state_code(v.get("state") or v.get("state_province"),
                                 bank["state"]),
                zip5=clean_zip(v.get("zip")), phone=clean_phone(v.get("phone")),
                website=clean(v.get("website")) or None, lat=v.get("geo_lat"),
                lng=v.get("geo_lng"), type_text=bank.get("type_text", ""),
                uid=v.get("id")))
        if page >= (data.get("total_pages") or 1):
            return rows
        page += 1


# --- per-bank custom parsers ----------------------------------------------------------------------

def _balanced_array(text, start):
    """Extract a balanced [...] JSON segment starting at text[start] == '['."""
    depth, k, in_str, esc = 0, start, False, False
    while k < len(text):
        ch = text[k]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
        elif ch == '"':
            in_str = True
        elif ch == "[":
            depth += 1
        elif ch == "]":
            depth -= 1
            if depth == 0:
                return text[start:k + 1]
        k += 1
    raise SystemExit("unbalanced JSON array in page")


def parse_cleveland(bank, force):
    page = fetch_text(bank, bank["endpoint"], "page.html", force)
    m = re.search(r"var locations_json = \[", page)
    if not m:
        raise SystemExit("locations_json not found - layout changed")
    rows = []
    for r in json.loads(_balanced_array(page, m.end() - 1)):
        if not clean(r.get("title")):
            continue
        pairs = [(DAY_NAMES.get(d), (v or {}).get("text") or "")
                 for d, v in (r.get("hours") or {}).items() if isinstance(v, dict)]
        # only take plain weekly windows; "Second Monday 4:30 PM..." drops out
        pairs = [(d, t) for d, t in pairs
                 if d and not re.search(r"first|second|third|fourth|last|\d(st|nd|rd|th)", t, re.I)]
        rows.append(row(
            r["title"], street=clean(r.get("address")) or None,
            city=clean(r.get("city")) or None, state="oh",
            zip5=clean_zip(r.get("zip")), phone=clean_phone(r.get("phone")),
            lat=r.get("lat"), lng=r.get("lng"), hours=hours_from_pairs(pairs),
            type_text=clean(r.get("category_title")), uid=r.get("id")))
    return rows


def parse_ozarks(bank, force):
    page = fetch_text(bank, bank["endpoint"], "page.html", force)
    m = re.search(r"window\.locationsData = \[", page)
    if not m:
        raise SystemExit("locationsData not found - layout changed")
    rows = []
    for r in json.loads(_balanced_array(page, m.end() - 1)):
        name = clean(r.get("title"))
        if not name:
            continue
        street = clean(f"{r.get('street_number') or ''} {r.get('street_name_short') or ''}") \
            or (clean(r.get("address")).split(",")[0] or None)
        rows.append(row(
            name, street=street or None, city=clean(r.get("city")) or None,
            state=state_code(r.get("state_short"), "mo"),
            zip5=clean_zip(r.get("post_code")), lat=r.get("lat"),
            lng=r.get("lng"), uid=r.get("loc_id")))
    return rows


def parse_feedwm(bank, force):
    page = fetch_text(bank, bank["endpoint"], "page.html", force)
    m = re.search(r"fafpfixed\s*=\s*\[", page)
    if not m:
        raise SystemExit("fafpfixed array not found - layout changed")
    rows = []
    for r in json.loads(_balanced_array(page, m.end() - 1)):
        if not clean(r.get("AgencyName")):
            continue
        rows.append(row(
            r["AgencyName"], street=clean(r.get("Addr1")) or None,
            city=clean(r.get("City")) or None,
            state=state_code(r.get("State"), "mi"), zip5=clean_zip(r.get("Zip")),
            phone=clean_phone(r.get("Phone")),
            email=clean(r.get("Email")) or None,
            website=clean(r.get("web")) or None, lat=r.get("Lat"),
            lng=r.get("Lng"), uid=r.get("Agency")))
    return rows


def parse_feedindiana(bank, force):
    page = fetch_text(bank, bank["endpoint"], "page.html", force)
    m = re.search(r"jQuery\.extend\(Drupal\.settings,\s*(\{.*?\})\);", page, re.S)
    if not m:
        raise SystemExit("Drupal.settings not found - layout changed")
    settings = json.loads(m.group(1))
    maps = settings.get("gmap") or {}
    rows = []
    for mp in maps.values():
        for mk in mp.get("markers") or []:
            text = mk.get("text") or ""
            nm = re.search(r"<h4><a[^>]*>(.*?)</a></h4>", text, re.S)
            if not nm:
                continue
            street_m = re.search(r'itemprop="streetAddress">(.*?)</span>', text, re.S)
            city_m = re.search(r'itemprop="addressLocality">(.*?)</span>', text, re.S)
            state_m = re.search(r'itemprop="addressRegion">(.*?)</span>', text, re.S)
            zip_m = re.search(r'itemprop="postalCode">(.*?)</span>', text, re.S)
            rows.append(row(
                strip_tags(nm.group(1)),
                street=strip_tags(street_m.group(1)) if street_m else None,
                city=strip_tags(city_m.group(1)) if city_m else None,
                state=state_code(state_m.group(1) if state_m else "", "in"),
                zip5=clean_zip(strip_tags(zip_m.group(1)) if zip_m else ""),
                lat=mk.get("latitude"), lng=mk.get("longitude")))
    return rows


def parse_daretocare(bank, force):
    page = fetch_text(bank, bank["endpoint"], "page.html", force)
    m = re.search(r"window\.FWP_JSON = (\{.*?\});", page)
    if not m:
        raise SystemExit("FWP_JSON not found - layout changed")
    pins = json.loads(m.group(1))["preload_data"]["settings"]["map"]["locations"]
    geo_by_post = {p["post_id"]: p["position"] for p in pins if p.get("post_id")}
    rows, pageno = [], 1
    while True:
        posts = fetch_json(
            bank, f"https://daretocare.org/wp-json/wp/v2/location?per_page=100&page={pageno}",
            f"rest-p{pageno}.json", force)
        for p in posts:
            pos = geo_by_post.get(p["id"])
            name = strip_tags((p.get("title") or {}).get("rendered") or "")
            if not pos or not name:
                continue
            # the REST payload has no address; state comes from the pin below
            rows.append(row(name, state=None, website=clean(p.get("link")) or None,
                            lat=pos.get("lat"), lng=pos.get("lng"), uid=p.get("id")))
        if len(posts) < 100:
            return rows
        pageno += 1


def parse_northcountry(bank, force):
    page = fetch_text(bank, bank["endpoint"], "page.html", force)
    heads = list(re.finditer(
        r'<h3 class="fl-heading">\s*(?:<a\s+href="([^"]*)"[^>]*>)?\s*'
        r'<span class="fl-heading-text">(.*?)</span>', page, re.S))
    rows = []
    for i, hm in enumerate(heads):
        seg = page[hm.end(): heads[i + 1].start() if i + 1 < len(heads) else len(page)]
        am = re.search(r'<div class="fl-rich-text">\s*<p>(?:<a[^>]*>)?(.*?)(?:</a>)?</p>',
                       seg, re.S)
        street = city = st = zip5 = None
        if am:
            lines = [strip_tags(x) for x in re.split(r"<br ?/?>", am.group(1))]
            lines = [x for x in lines if x]
            cm = None
            if lines:
                cm = re.match(r"^(.+?)[, ]+([A-Z]{2}),?\s*(\d{5})?$", lines[-1])
            if cm:
                city, st, zip5 = cm.group(1).strip(" ,"), state_code(cm.group(2)), cm.group(3)
                street = ", ".join(lines[:-1]) or None
        rows.append(row(strip_tags(hm.group(2)), street=street, city=city,
                        state=st or bank["state"], zip5=zip5))
    return rows


def parse_godspantry(bank, force):
    page = fetch_text(bank, bank["endpoint"], "page.html", force)
    rows = []
    for tag in re.findall(r'<div[^>]*class="location w-dyn-item"[^>]*>', page):
        attrs = dict(re.findall(r'data-([a-z-]+)="([^"]*)"', tag))
        name = clean(htmllib.unescape(attrs.get("name", "")))
        if not name:
            continue
        street, city, st, zip5 = parse_oneline(attrs.get("address"), "ky")
        pairs = [(d, attrs.get(day, "")) for day, d in DAY_NAMES.items()]
        rows.append(row(
            name, street=street, city=city, state=st or "ky", zip5=zip5,
            phone=clean_phone(attrs.get("phone")),
            email=clean(attrs.get("email")) or None, lat=attrs.get("lat"),
            lng=attrs.get("lng"), hours=hours_from_pairs(pairs),
            type_text=clean(attrs.get("tag")), uid=attrs.get("id") or None))
    return rows


def parse_mfbn(bank, force):
    page = fetch_text(bank, bank["endpoint"], "page.html", force)
    rows = []
    for tag in re.findall(r'<div id="post-\d+" class="marker[^>]*>', page):
        attrs = dict(re.findall(r'data-([a-z-]+)="([^"]*)"', tag))
        name = clean(htmllib.unescape(attrs.get("title", "")))
        latlng = (attrs.get("latlng") or ",").split(",")
        if not name:
            continue
        pid = re.search(r'id="post-(\d+)"', tag)
        rows.append(row(
            name, street=clean(htmllib.unescape(attrs.get("address", ""))) or None,
            city=clean(attrs.get("city")) or None,
            state=state_code(attrs.get("state"), "mt"),
            zip5=clean_zip(attrs.get("zip")), lat=latlng[0], lng=latlng[1],
            type_text=clean(attrs.get("types")),
            uid=pid.group(1) if pid else None))
    return rows


def parse_ccs(bank, force):
    page = fetch_text(bank, bank["endpoint"], "page.html", force)
    rows = []
    for m in re.finditer(r'<div class="mpfy-card mpfy-card-(\d+)">', page):
        end = page.find("mpfy-card ", m.end())
        card = page[m.end(): end if end > 0 else len(page)]
        nm = re.search(r"<h2>(.*?)</h2>", card, re.S)
        if not nm:
            continue
        prog = re.search(r'mpfy-card-program-name">(.*?)</h3>', card, re.S)
        tel = re.search(r'href="tel:([^"]+)"', card)
        addr_m = re.search(r"<h3>Address</h3>\s*<span[^>]*>(.*?)</span>", card, re.S)
        geo_m = re.search(r"/@(-?\d+\.\d+),(-?\d+\.\d+)", card)
        street = city = st = zip5 = None
        if addr_m:
            lines = [strip_tags(x) for x in re.split(r"<br ?/?>", addr_m.group(1))]
            lines = [x for x in lines if x]
            if lines:
                cm = re.match(r"^(.+?)\s+([A-Z]{2})\s+(\d{5})", lines[-1])
                if cm:
                    city, st, zip5 = cm.group(1), state_code(cm.group(2)), cm.group(3)
                    street = ", ".join(lines[:-1]) or None
        rows.append(row(
            strip_tags(nm.group(1)), street=street, city=city,
            state=st or "ca", zip5=zip5,
            phone=clean_phone(tel.group(1)) if tel else None,
            lat=geo_m.group(1) if geo_m else None,
            lng=geo_m.group(2) if geo_m else None,
            type_text=strip_tags(prog.group(1)) if prog else "", uid=m.group(1)))
    return rows


def parse_fbd(bank, force):
    page = fetch_text(bank, bank["endpoint"], "page.html", force)
    rows = []
    for p in re.findall(r"<p>(.*?)</p>", page, re.S):
        lines = [strip_tags(x) for x in re.split(r"<br ?/?>", p)]
        lines = [x for x in lines if x]
        zi = next((i for i, x in enumerate(lines)
                   if re.search(r",\s*DE\s+\d{5}", x)), None)
        if zi is None or zi < 2:
            continue
        cm = re.match(r"^(.+?),\s*DE\s+(\d{5})", lines[zi])
        phone = next((clean_phone(x) for x in lines
                      if re.search(r"phone", x, re.I) and clean_phone(x)), None)
        rows.append(row(
            lines[0], street=lines[1], street2=", ".join(lines[2:zi]) or None,
            city=cm.group(1), state="de", zip5=cm.group(2), phone=phone))
    return rows


def parse_iowa(bank, force):
    data = fetch_json(bank, bank["endpoint"], "dump.json", force)
    keep = set(bank.get("keep") or [])
    rows = []
    for r in data:
        if not clean(r.get("name")) or (keep and clean(r.get("category")) not in keep):
            continue
        rows.append(row(
            r["name"], street=clean(r.get("street")) or None,
            city=clean(r.get("city")) or None,
            state=state_code(r.get("state"), "ia"),
            zip5=clean_zip(r.get("postalcode")),
            phone=clean_phone(r.get("phone")),
            website=clean(r.get("website")) or None, lat=r.get("latitude"),
            lng=r.get("longitude"),
            type_text="meal site" if clean(r.get("category")) == "meal-site" else "",
            uid=r.get("id")))
    return rows


def parse_smfoodbank(bank, force):
    page = fetch_text(bank, bank["endpoint"], "page.html", force)
    rows = []
    for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", page, re.S):
        tds = [strip_tags(td) for td in re.findall(r"<td[^>]*>(.*?)</td>", tr, re.S)]
        if len(tds) < 8 or not tds[0]:
            continue
        rows.append(row(
            tds[0], street=tds[2] or None, street2=tds[3] or None,
            city=tds[4] or None, state="mi", zip5=clean_zip(tds[5]),
            phone=clean_phone(tds[7]), type_text=tds[1]))
    return rows


def parse_mofc(bank, force):
    page = fetch_text(bank, bank["endpoint"], "page.html", force)
    rows = []
    for block in re.split(r'class="boxed-column-inner"', page)[1:]:
        block = block[:block.find("</a>")] if "</a>" in block else block
        nm = re.search(r"<h5>(.*?)</h5>", block, re.S)
        if not nm:
            continue
        name = strip_tags(nm.group(1))
        if "market" not in name.lower():
            name = f"Mid-Ohio Market {name}"
        ps = re.findall(r"<p[^>]*>(.*?)</p>", block, re.S)
        street = city = zip5 = phone = None
        pairs = []
        for p in ps:
            lines = [strip_tags(x) for x in re.split(r"<br ?/?>", p)]
            lines = [x for x in lines if x]
            for ln in lines:
                cm = re.match(r"^(.+?),\s*OH\s+(\d{5})", ln)
                dm = re.match(r"^([A-Za-z]+day):\s*(.+)$", ln)
                if cm:
                    city, zip5 = cm.group(1), cm.group(2)
                elif dm and DAY_NAMES.get(dm.group(1).lower()):
                    pairs.append((DAY_NAMES[dm.group(1).lower()], dm.group(2)))
                elif not phone and clean_phone(ln):
                    phone = clean_phone(ln)
                elif not city and re.match(r"^\d+ ", ln):
                    street = ln.rstrip(",")
        rows.append(row(name, street=street, city=city, state="oh", zip5=zip5,
                        phone=phone, hours=hours_from_pairs(pairs)))
    return rows


def parse_mountaineer(bank, force):
    page = fetch_text(bank, bank["endpoint"], "page.html", force)
    rows = []
    for h2 in re.findall(r"<h2[^>]*>(.*?)</h2>", page, re.S):
        text = re.sub(r"<br[^>]*>", "\n", h2)
        lines = [clean(htmllib.unescape(re.sub(r"<[^>]+>", "", x)))
                 for x in text.split("\n")]
        lines = [x for x in lines if x]
        if len(lines) < 2:
            continue
        am = re.match(r"^(.+?)\s*\|\s*(.+?),\s*WV\s*(\d{5})", lines[1])
        if not am:
            continue
        rows.append(row(lines[0], street=am.group(1), city=am.group(2),
                        state="wv", zip5=am.group(3),
                        type_text="mobile pantry stop"))
    return rows


def _balanced_object(text, key_idx):
    """Extract the {...} JSON object enclosing text[key_idx]."""
    depth, i = 0, key_idx
    while i >= 0:
        ch = text[i]
        if ch == "}":
            depth += 1
        elif ch == "{":
            if depth == 0:
                break
            depth -= 1
        i -= 1
    start = i
    depth, in_str, esc, j = 0, False, False, start
    while j < len(text):
        ch = text[j]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
        elif ch == '"':
            in_str = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start:j + 1]
        j += 1
    return None


def parse_shsv(bank, force):
    """Second Harvest of Silicon Valley mm-food-locator admin-ajax dump."""
    data = fetch_json(bank, bank["endpoint"], "dump.json", force)
    rows = []
    for r in (data.get("locations") or {}).values():
        if not clean(r.get("name")):
            continue
        rows.append(row(
            r["name"], street=clean(r.get("street")) or None,
            city=clean(r.get("city")) or None,
            state=state_code(r.get("state"), bank["state"]),
            zip5=clean_zip(r.get("zip")), lat=r.get("lat"), lng=r.get("lng"),
            uid=r.get("siteId")))
    return rows


def parse_feedingsga(bank, force):
    """Second Harvest of South Georgia: DATA array inline in the map-init JS."""
    text = fetch_text(bank, bank["endpoint"], "init.js", force)
    m = re.search(r"var DATA = \[", text)
    if not m:
        raise SystemExit("DATA array not found - pantry-finder-init.js changed")
    rows = []
    for r in json.loads(_balanced_array(text, m.end() - 1)):
        name = clean(r.get("name"))
        if not name:
            continue
        city, st = clean(r.get("city")), None
        cm = re.match(r"^(.*?),\s*([A-Za-z]{2})\.?$", city)
        if cm:
            city, st = cm.group(1).strip(), state_code(cm.group(2))
        rows.append(row(
            name, street=clean(r.get("address")) or None, city=city or None,
            state=st or bank["state"], phone=clean_phone(r.get("phone")),
            website=clean(r.get("url")) or None, lat=r.get("lat"),
            lng=r.get("lng")))
    return rows


CH_DAYS = {"Mo": "mon", "Tu": "tue", "We": "wed", "Th": "thu", "Fr": "fri",
           "Sa": "sat", "Su": "sun"}


def parse_cityharvest(bank, force):
    """City Harvest food map: open pantry dataset behind the map iframe."""
    data = fetch_json(bank, bank["endpoint"], "dump.json", force)
    rows = []
    for r in data:
        name = clean(r.get("name"))
        if not name:
            continue
        entries = []
        for h in r.get("hours") or []:
            days = [CH_DAYS[d] for d in h.get("days") or [] if d in CH_DAYS]
            open_t = (h.get("timeStart") or "")[:5]
            close_t = (h.get("timeEnd") or "")[:5]
            if days and re.match(r"^\d{2}:\d{2}$", open_t) \
                    and re.match(r"^\d{2}:\d{2}$", close_t) and open_t < close_t:
                entries.append(Flow(days=sorted(days, key=DAY_TOKENS.index),
                                    open=open_t, close=close_t))
        phones = r.get("phoneNumbers") or []
        phone = clean_phone(phones[0].get("phoneNumber")) if phones else None
        geo = (r.get("geolocation") or {}).get("coordinates") or [None, None]
        rows.append(row(
            name, street=clean(r.get("streetAddress")) or None,
            city=clean(r.get("addressLocality")) or None,
            state=state_code(r.get("addressRegion"), "ny"),
            zip5=clean_zip(r.get("postalCode")), phone=phone,
            website=clean(r.get("website")) or None, lat=geo[1], lng=geo[0],
            hours=entries or None, uid=r.get("id")))
    return rows


def parse_licares(bank, force):
    """Long Island Cares: Cloudflare-worker JSON behind the mapbox map."""
    data = fetch_json(bank, bank["endpoint"], "dump.json", force)
    rows = []
    for r in data.get("result") or []:
        name = clean(r.get("name"))
        if not name:
            continue
        rows.append(row(
            name, street=clean(r.get("address")) or None,
            street2=clean(r.get("address2")) or None,
            city=clean(r.get("city")) or None,
            state=state_code(r.get("state"), "ny"),
            zip5=clean_zip(r.get("zip")),
            phone=clean_phone(r.get("description")), lat=r.get("lat"),
            lng=r.get("lng"), uid=r.get("id")))
    return rows


def parse_sitewrench(bank, force):
    """Mid-South Food Bank: SiteWrench locator-map Places dump."""
    data = fetch_json(bank, bank["endpoint"], "dump.json", force)
    rows = []
    for r in data.get("Places") or []:
        name = clean(r.get("Name"))
        street = clean(r.get("Address"))
        if not name or not street:
            continue  # county headers and empty markers
        lat, lng = r.get("CenterPointLat"), r.get("CenterPointLong")
        if (lat, lng) == (37.09024, -95.712891):  # widget default US center
            lat = lng = None
        rows.append(row(
            name, street=street, city=clean(r.get("City")) or None,
            state=state_code(r.get("State"), bank["state"]),
            zip5=clean_zip(r.get("Zipcode")), phone=clean_phone(r.get("Phone")),
            website=clean(r.get("Url")) or None, lat=lat, lng=lng,
            type_text=clean(r.get("Description")), uid=r.get("PlaceId")))
    return rows


FEEDINGSD_QUERY = """query { entries(section: "locations", limit: 600) {
  id title
  ... on location_Entry {
    locationMap { lat lng parts { number address city state postcode } }
    foodDistributionPhoneNumber
  }
} }"""


def parse_feedingsd(bank, force):
    """Feeding South Dakota: Craft CMS public GraphQL."""
    data = cache_json(bank, "dump.json", force, lambda: post_bytes(
        bank["endpoint"], json.dumps({"query": FEEDINGSD_QUERY}).encode(),
        {"Content-Type": "application/json"}))
    rows = []
    for r in (data.get("data") or {}).get("entries") or []:
        name = clean(r.get("title"))
        lm = r.get("locationMap") or {}
        parts = lm.get("parts") or {}
        if not name:
            continue
        street = clean(f"{parts.get('number') or ''} {parts.get('address') or ''}") or None
        rows.append(row(
            name, street=street, city=clean(parts.get("city")) or None,
            state=state_code(parts.get("state"), "sd"),
            zip5=clean_zip(parts.get("postcode")),
            phone=clean_phone(r.get("foodDistributionPhoneNumber")),
            lat=lm.get("lat"), lng=lm.get("lng"), uid=r.get("id")))
    return rows


FOODNOW_QUERY = """query getLocations($where: RootQueryToLocationConnectionWhereArgs, $first: Int) {
  locations(where: $where, first: $first) {
    nodes { id locationFields {
      agencyIdentifier addressLine1 addressLine2 archive city displayName
      fbcAgencyCategoryCode zipCode latitude longitude } } } }"""


def parse_foodnow(bank, force):
    """Alameda County CFB foodnow.net: headless-WP GraphQL locations."""
    url = f"{bank['endpoint']}?" + urllib.parse.urlencode({
        "graphql": "", "query": FOODNOW_QUERY,
        "variables": json.dumps({"where": {"language": "EN"}, "first": 1000})})
    data = fetch_json(bank, url, "dump.json", force)
    rows = []
    for node in data["data"]["locations"]["nodes"]:
        f = node.get("locationFields") or {}
        name = clean(f.get("displayName"))
        if not name or f.get("archive"):
            continue
        rows.append(row(
            name, street=clean(f.get("addressLine1")) or None,
            street2=clean(f.get("addressLine2")) or None,
            city=clean(f.get("city")) or None, state="ca",
            zip5=clean_zip(f.get("zipCode")), lat=f.get("latitude"),
            lng=f.get("longitude"),
            type_text=clean(f.get("fbcAgencyCategoryCode")),
            uid=f.get("agencyIdentifier") or node.get("id")))
    return rows


def parse_fbnyc(bank, force):
    """Food Bank For NYC: agency×day CSV behind the Azure-hosted map."""
    text = fetch_text(bank, bank["endpoint"], "dump.csv", force)
    sites: dict[tuple, dict] = {}
    for r in csv.DictReader(io.StringIO(text.lstrip("\ufeff"))):
        name = clean((r.get("Agency") or "").split(" : ")[0])
        street = clean(r.get("Address 1"))
        if not name or clean(r.get("Inactive")).lower() == "yes":
            continue
        key = (norm(name), norm(street))
        site = sites.setdefault(key, {
            "name": name, "street": street or None,
            "city": clean(r.get("Address 3")) or None,
            "zip": clean_zip(r.get("Address 4")),
            "phone": clean_phone(r.get("Phone")), "lat": r.get("Latitude"),
            "lng": r.get("Longitude"),
            "type": clean(r.get("Program Type")), "pairs": []})
        day = DAY_NAMES.get(clean(r.get("Day of the Week")).lower())
        o, c = clean(r.get("Opening Hour")), clean(r.get("Closing Hour"))
        freq = clean(r.get("Frequency")).lower()
        if day and o and c and freq in ("", "weekly", "every week"):
            site["pairs"].append((day, f"{o} - {c}"))
    return [row(s["name"], street=s["street"], city=s["city"], state="ny",
                zip5=s["zip"], phone=s["phone"], lat=s["lat"], lng=s["lng"],
                hours=hours_from_pairs(s["pairs"]), type_text=s["type"])
            for s in sites.values()]


def parse_sfmarin(bank, force):
    """SF-Marin food locator: Laravel app, XSRF cookie + POST /resource."""
    def produce(county):
        import http.cookiejar
        jar = http.cookiejar.CookieJar()
        opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(jar))
        req = urllib.request.Request(f"{bank['endpoint']}/en/{county}",
                                     headers={"User-Agent": BROWSER_UA})
        opener.open(req, timeout=120).read()
        token = urllib.parse.unquote(
            next(c.value for c in jar if c.name == "XSRF-TOKEN"))
        body = {"visit_county": county, "visit_zip": "unknown",
                "visit_senior": "0", "visit_urgent": "0", "visit_disabled": "0",
                "visit_lang": "en", "visit_calfresh": "0", "visit_hdg": "0"}
        time.sleep(1.0)
        req = urllib.request.Request(
            f"{bank['endpoint']}/resource", data=json.dumps(body).encode(),
            headers={"User-Agent": BROWSER_UA, "Content-Type": "application/json",
                     "X-XSRF-TOKEN": token, "X-Requested-With": "XMLHttpRequest"})
        return opener.open(req, timeout=120).read()

    rows = []
    for county in bank["counties"]:
        data = cache_json(bank, f"{county}.json", force,
                          lambda c=county: produce(c))
        for r in data.get("ngns") or []:
            name = clean(r.get("name"))
            if not name:
                continue
            pairs = []
            if r.get("distro_day") and r.get("distro_start") and r.get("distro_end"):
                token_day = DAY_NAMES.get(clean(r["distro_day"]).lower())
                if token_day:
                    pairs.append((token_day,
                                  f"{r['distro_start']} - {r['distro_end']}"))
            rows.append(row(
                name, street=clean(r.get("address")) or None,
                city=clean(r.get("city")) or None, state="ca",
                zip5=clean_zip(r.get("zip")), phone=clean_phone(r.get("phone")),
                lat=r.get("lat"), lng=r.get("lng"),
                hours=hours_from_pairs(pairs), uid=r.get("id")))
    return rows


def parse_semo(bank, force):
    """Southeast Missouri FB: county-accordion static pantry list."""
    page = fetch_text(bank, bank["endpoint"], "page.html", force)
    rows = []
    # several pantries share one <p>; each starts with a <strong>NAME</strong>
    for p in re.findall(r"<strong>(.*?)</strong>(.*?)(?=<strong>|</p>)",
                        page, re.S):
        name = strip_tags(p[0])
        lines = [strip_tags(x) for x in re.split(r"<br\s*/?>", p[1])]
        lines = [x for x in lines if x]
        if not name or not lines:
            continue
        street = city = zip5 = phone = None
        for ln in lines:
            cm = re.match(r"^(.+?),\s*MO\.?\s*(\d{5})?", ln, re.I)
            if cm and not city:
                city, zip5 = cm.group(1).title().strip(" ,"), cm.group(2)
            elif not phone and clean_phone(ln):
                phone = clean_phone(ln)
            elif not street and re.match(r"^\d+ ", ln):
                street = ln.rstrip(",")
        if not city:
            continue  # not an address block (intro copy etc.)
        rows.append(row(name.title() if name.isupper() else name,
                        street=street, city=city, state="mo", zip5=zip5,
                        phone=phone))
    return rows


def parse_setx(bank, force):
    """Southeast Texas FB: Connections-plugin per-county agency pages."""
    rows = []
    for county in bank["counties"]:
        page = fetch_text(bank, bank["endpoint"].format(county=county),
                          f"{county}.html", force)
        for block in re.split(r'class="cn-list-row', page)[1:]:
            nm = re.search(r'<span class="org fn notranslate">(.*?)</span>', block, re.S)
            if not nm:
                continue
            def span(cls):
                m = re.search(rf'class="{cls}[^"]*">(.*?)</span>', block, re.S)
                return strip_tags(m.group(1)) if m else None
            tel = re.search(r'class="value">(.*?)</span>', block, re.S)
            rows.append(row(
                strip_tags(nm.group(1)), street=span("street-address"),
                city=span("locality"), state=state_code(span("region"), "tx"),
                zip5=clean_zip(span("postal-code")),
                phone=clean_phone(tel.group(1)) if tel else None,
                type_text=""))
    return rows


def parse_gulfcoast(bank, force):
    """Feeding the Gulf Coast: server-rendered pantry search results."""
    url = f"{bank['endpoint']}?" + urllib.parse.urlencode({
        "address": "Mobile, AL", "near": "200", "pantry": "3102",
        "distribution": "3101", "soup-kitchen": "3247", "seniors": "3099"})
    page = fetch_text(bank, url, "results.html", force)
    rows = []
    for block in re.split(r'<div class="pantry-result">', page)[1:]:
        nm = re.search(r'<p class="epsilon">(.*?)</p>', block, re.S)
        ad = re.search(r'<p class="street">(.*?)</p>', block, re.S)
        if not nm or not ad:
            continue
        lines = [strip_tags(x) for x in re.split(r"<br\s*/?>", ad.group(1))]
        lines = [x for x in lines if x]
        street = lines[0] if lines else None
        city = st = zip5 = None
        if len(lines) > 1:
            cm = re.match(r"^(.+?),\s*([A-Z]{2})\s*(\d{5})?", lines[-1])
            if cm:
                city, st, zip5 = cm.group(1), state_code(cm.group(2)), cm.group(3)
        ph = re.search(r'<p class="phone-number[^"]*">(.*?)</p>', block, re.S)
        rows.append(row(
            strip_tags(nm.group(1)), street=street, city=city,
            state=st or bank["state"], zip5=zip5,
            phone=clean_phone(strip_tags(ph.group(1))) if ph else None))
    return rows


def parse_harvesters(bank, force):
    """Harvesters: server-rendered locator results (statewide 500mi search)."""
    url = f"{bank['endpoint']}?" + urllib.parse.urlencode(
        {"zip": "Kansas City, MO", "radius": "500"})
    page = fetch_text(bank, url, "results.html", force)
    rows, seen = [], set()
    for block in re.split(r'class="location-result', page)[1:]:
        nm = re.search(r'<h6[^>]*>(.*?)</h6>', block, re.S)
        ad = re.search(r'<p class="mb-0">(.*?)</p>', block, re.S)
        if not nm or not ad:
            continue
        name = strip_tags(nm.group(1))
        lines = [strip_tags(x) for x in re.split(r"<br\s*/?>", ad.group(1))]
        lines = [x for x in lines if x]
        street = lines[0] if lines else None
        city = st = zip5 = phone = None
        for ln in lines[1:]:
            cm = re.match(r"^(.+?),\s*([A-Z]{2})\s*(\d{5})?", ln)
            if cm:
                city, st, zip5 = cm.group(1), state_code(cm.group(2)), cm.group(3)
            elif clean_phone(ln):
                phone = clean_phone(ln)
        key = (norm(name), norm(street or ""), norm(city or ""))
        if key in seen:
            continue  # desktop + mobile markup renders each result twice
        seen.add(key)
        alt = re.search(r'alt="([^"]+)"', block)
        type_text = alt.group(1) if alt else ""
        if type_text.lower() == "kitchen":
            type_text = "meal site"
        rows.append(row(name, street=street, city=city, state=st or "mo",
                        zip5=zip5, phone=phone, type_text=type_text))
    return rows


def parse_theshfb(bank, force):
    """Second Harvest Clark/Champaign/Logan: Wix warmupData collection items."""
    page = fetch_text(bank, bank["endpoint"], "page.html", force)
    recs = {}
    for m in re.finditer(r'"agencyName":"', page):
        obj = _balanced_object(page, m.start())
        if not obj:
            continue
        try:
            d = json.loads(obj)
        except ValueError:
            continue
        if clean(d.get("agencyName")):
            recs[d["_id"] if d.get("_id") else d["agencyName"]] = d
    rows = []
    for uid, d in recs.items():
        street, city, st, zip5 = parse_oneline(d.get("physicalAddress"), "oh")
        rows.append(row(
            d["agencyName"], street=(street or "").split(",")[0] or None,
            city=clean(d.get("city")) or city,
            state=state_code(d.get("state"), st or "oh"),
            zip5=clean_zip(d.get("zip")) or zip5,
            phone=clean_phone(d.get("phoneNumber")), uid=uid))
    return rows


def parse_akhubdb(bank, force):
    """Food Bank of Alaska: HubDB agency-partner table (name/city/website)."""
    data = fetch_json(bank, bank["endpoint"], "dump.json", force)
    rows = []
    for r in data.get("objects") or []:
        v = r.get("values") or {}
        name = clean(v.get("1"))
        if not name:
            continue
        website = clean(v.get("8"))
        rows.append(row(name, city=clean(v.get("4")) or None, state="ak",
                        website=website or None, uid=r.get("id")))
    return rows


def parse_pantryhawk(bank, force):
    """Second Harvest NW PA: pantry-hawk nearest-15 search swept over the
    service-area towns; the nonce is read fresh from the locator page."""
    def produce(addr):
        from .util import get as util_get
        page = util_get(f"{bank['endpoint']}/need-help/agency-locator/",
                        ua=BROWSER_UA).decode("utf-8", "replace")
        m = re.search(r'LSAjax = \{"security":"(\w+)"', page)
        if not m:
            raise SystemExit("pantry-hawk nonce not found - page changed")
        fields = [("LocationSearch_Address", addr),
                  ("LocationSearch_Category", "12011")]
        params = {"action": "locationsearch", "security": m.group(1)}
        for i, (n, val) in enumerate(fields):
            params[f"form_data[{i}][name]"] = n
            params[f"form_data[{i}][value]"] = val
        return post_bytes(
            f"{bank['endpoint']}/wp-admin/admin-ajax.php",
            urllib.parse.urlencode(params).encode(),
            {"Content-Type": "application/x-www-form-urlencoded"})

    rows, seen = [], set()
    for k, addr in enumerate(bank["addresses"]):
        data = cache_json(bank, f"search-{k:02d}.json", force,
                          lambda a=addr: produce(a))
        if "locationsFound" not in data:
            raise SystemExit(f"pantry-hawk error: {str(data)[:150]}")
        for r in json.loads(data["locationsFound"]):
            if r.get("id") in seen or not clean(r.get("loc_name")):
                continue
            seen.add(r.get("id"))
            pairs = []
            for day in DAY_TOKENS:
                try:
                    windows = json.loads(r.get(f"loc_{day}_hrs") or "[]")
                except ValueError:
                    continue
                for w in windows:
                    if isinstance(w, list) and len(w) == 2 and w[0] and w[1]:
                        pairs.append((day, f"{w[0]} - {w[1]}"))
            pm = re.match(r"POINT\((-?[\d.]+) (-?[\d.]+)\)", r.get("loc_point") or "")
            rows.append(row(
                r["loc_name"], street=clean(r.get("loc_address_1")) or None,
                street2=clean(r.get("loc_address_2")) or None,
                city=clean(r.get("loc_city")) or None,
                state=state_code(r.get("loc_state"), "pa"),
                zip5=clean_zip(r.get("loc_zipcode")),
                phone=clean_phone(r.get("loc_phone")),
                email=clean(r.get("loc_email")) or None,
                lat=pm.group(1) if pm else None,
                lng=pm.group(2) if pm else None,
                hours=hours_from_pairs(pairs), uid=r.get("id")))
    return rows


HARVESTERS = {
    "wpsl": harvest_wpsl, "wpgmza": harvest_wpgmza, "asl": harvest_asl,
    "slp": harvest_slp, "storepoint": harvest_storepoint,
    "storerocket": harvest_storerocket, "mymaps": harvest_mymaps,
    "arcgis": harvest_arcgis, "ssf": harvest_ssf,
    "foodfinder": harvest_foodfinder, "mapsvg": harvest_mapsvg,
    "slw": harvest_slw, "freshtrak": harvest_freshtrak,
    "tribevenues": harvest_tribevenues,
}
PARSERS = {
    "cleveland": parse_cleveland, "ozarks": parse_ozarks,
    "feedwm": parse_feedwm, "feedindiana": parse_feedindiana,
    "daretocare": parse_daretocare, "northcountry": parse_northcountry,
    "godspantry": parse_godspantry, "mfbn": parse_mfbn, "ccs": parse_ccs,
    "fbd": parse_fbd, "iowa": parse_iowa, "smfoodbank": parse_smfoodbank,
    "mofc": parse_mofc, "mountaineer": parse_mountaineer,
    "shsv": parse_shsv, "feedingsga": parse_feedingsga,
    "cityharvest": parse_cityharvest, "licares": parse_licares,
    "sitewrench": parse_sitewrench, "feedingsd": parse_feedingsd,
    "foodnow": parse_foodnow, "fbnyc": parse_fbnyc, "sfmarin": parse_sfmarin,
    "semo": parse_semo, "setx": parse_setx, "gulfcoast": parse_gulfcoast,
    "harvesters": parse_harvesters, "theshfb": parse_theshfb,
    "akhubdb": parse_akhubdb, "pantryhawk": parse_pantryhawk,
}
# verified.method: structured data feeds are api; parsed HTML pages are scrape
API_PLATFORMS = {"wpsl", "wpgmza", "asl", "slp", "storepoint", "storerocket",
                 "mymaps", "arcgis", "ssf", "mapsvg", "slw", "freshtrak",
                 "tribevenues"}
API_PARSERS = {"iowa", "daretocare", "shsv", "cityharvest", "licares",
               "sitewrench", "feedingsd", "foodnow", "fbnyc", "sfmarin",
               "akhubdb", "pantryhawk"}


def harvest(bank, force):
    if bank["platform"] == "custom":
        return PARSERS[bank["parser"]](bank, force)
    return HARVESTERS[bank["platform"]](bank, force)


def build_record(bank, raw, places, source_id):
    name = raw["name"]
    if len(name) < 2:
        return None
    state = raw.get("state")
    if state not in places.by_state:
        state = None
    geo = to_geo(raw.get("lat"), raw.get("lng"))
    if state is None:
        if not geo:
            return None
        near = places.nearest(geo["lat"], geo["lng"])
        if not near:
            return None
        state = near[0]

    city = clean(raw.get("city") or "")
    geoid, place_slug = places.resolve(state, city)
    if not geoid and geo:  # state-matched nearest fallback
        near = places.nearest(geo["lat"], geo["lng"])
        if near and near[0] == state:
            geoid, place_slug = near[1], near[2]
    if place_slug == "unknown" and not city:
        return None  # nothing to shard by - not a usable site record

    rec = {"_state": state, "_place_slug": place_slug, "_name": name,
           "org": bank["org"],
           "categories": classify(bank, name, raw.get("type") or "")}
    if city:
        rec["address"] = Flow({k: v for k, v in {
            "street": clean(raw.get("street") or "") or None,
            "street2": clean(raw.get("street2") or "") or None,
            "city": city, "state": state, "zip": raw.get("zip"),
        }.items() if v})
    if geoid:
        rec["place"] = geoid
    if geo:
        rec["geo"] = geo
    if raw.get("phone"):
        rec["phone"] = raw["phone"]
    email = clean(raw.get("email") or "")
    if "@" in email and " " not in email:
        rec["email"] = email
    website = clean(raw.get("website") or "")
    if re.match(r"^https?://\S+$", website):
        rec["website"] = website
    if raw.get("hours"):
        rec["hours"] = raw["hours"]
    if raw.get("uid") not in (None, ""):
        rec["external_ids"] = Flow({bank["id"]: str(raw["uid"])})
    rec["sources"] = [source_id]
    method = "api" if (bank["platform"] in API_PLATFORMS
                       or bank.get("parser") in API_PARSERS) else "scrape"
    rec["verified"] = Flow(on=today(), method=method)
    return rec


def dedupe_key(rec, raw):
    addr = rec.get("address") or {}
    street, city = norm(addr.get("street") or ""), norm(addr.get("city") or "")
    if street or city:
        return (norm(rec["_name"]), street, city)
    geo = rec.get("geo") or {}
    return (norm(rec["_name"]), round(geo.get("lat", 0), 3),
            round(geo.get("lng", 0), 3))


def main(argv):
    force = "--force" in argv
    dry = "--dry" in argv
    only = [a for a in argv if not a.startswith("-")]
    places = Places()
    registry = load_yaml(REGISTRY)
    if only:
        registry = [b for b in registry if b["id"] in only or b["org"] in only]
        if not registry:
            raise SystemExit(f"no registry banks match {only}")
        if not dry:
            raise SystemExit("bank selection is only allowed with --dry - the "
                             "module owns the whole foodbank/ family and a "
                             "partial write would drop every other bank")

    records, seen, skipped, banks_ok = [], {}, [], 0
    cross_dupes = within_dupes = 0
    for bank in registry:
        try:
            raws = harvest(bank, force)
        except (Exception, SystemExit) as e:  # noqa: BLE001 - per-bank isolation
            print(f"foodbank: SKIPPING {bank['id']}: {e}")
            skipped.append(bank["id"])
            continue
        source_id = f"foodbank/{bank['id']}"
        kept = 0
        bank_seen = set()
        for raw in raws:
            rec = build_record(bank, raw, places, source_id)
            if rec is None:
                continue
            key = dedupe_key(rec, raw)
            if key in bank_seen:
                within_dupes += 1
                continue
            bank_seen.add(key)
            if key in seen:
                cross_dupes += 1
                continue
            seen[key] = bank["id"]
            records.append(rec)
            kept += 1
        if kept < bank["floor"]:
            print(f"foodbank: SKIPPING {bank['id']}: only {kept} records "
                  f"(floor {bank['floor']})")
            skipped.append(bank["id"])
            records = [r for r in records if r["sources"] != [source_id]]
            seen = {k: v for k, v in seen.items() if v != bank["id"]}
            continue
        if not dry:
            write_source(
                "foodbank", bank["id"], kind="directory",
                publisher=bank["name"],
                title=f"{bank['name']} pantry/agency locator",
                url=bank["url"], tier="secondary",
            )
        banks_ok += 1
        print(f"foodbank/{bank['id']}: {kept}/{len(raws)} kept")

    print(f"foodbank: {banks_ok} banks, {len(records)} records "
          f"({within_dupes} within-bank dupes, {cross_dupes} cross-bank dupes)")
    if skipped:
        print(f"foodbank: skipped banks: {', '.join(skipped)}")
    if dry:
        return
    if banks_ok < 45:
        raise SystemExit(f"foodbank: only {banks_ok} working banks - not writing")
    if len(records) < 6000:
        raise SystemExit(f"foodbank: only {len(records)} records - floor is 6,000; "
                         "not writing")
    replace_records("sites", "foodbank/", records)


if __name__ == "__main__":
    main(sys.argv[1:])
