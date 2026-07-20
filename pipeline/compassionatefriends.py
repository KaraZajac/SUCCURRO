"""The Compassionate Friends chapter locator -> org records (grief support
after the death of a child; family-support / peer-support).

The chapter locator runs WP Store Locator (wpsl). Its admin-ajax store_search
endpoint clamps max_results/search_radius server-side (10 results / 150 mi),
so the full pull instead uses the open WordPress REST API for the wpsl_stores
custom post type (~437 chapters; /wp-json/wp/v2/wpsl_stores) and then fetches
each chapter's permalink page, which embeds the structured location as JSON
(`wpslMap_0 = {"locations":[{store, address, address2, city, state, zip,
country, lat, lng, id}]}`) plus a wpsl-contact-details block (Phone / Email /
Url) and a "Chapter Number" heading. Pages are throttled (util.get) and cached
under sources/compassionatefriends/pages/. Non-US chapters (the locator also
lists a few international ones) are skipped; Puerto Rico is kept. wpsl's
"address" line is the meeting venue for many chapters — mapped to street/
street2 as published. Facts-only re-expression; meeting-schedule prose is not
copied.

Usage: python3 -m pipeline.compassionatefriends [--force]
"""
import html
import json
import re
import sys
from collections import Counter

from .emit import Places, replace_records, today, write_source
from .util import Flow, SOURCES, fetch

API = ("https://www.compassionatefriends.org/wp-json/wp/v2/wpsl_stores"
       "?per_page=100&page={page}&_fields=id,slug,link,title,class_list")
LOCATOR_URL = ("https://www.compassionatefriends.org/find-support/chapters/"
               "chapter-locator/")

MAP_RE = re.compile(r"wpslMap_0 = ")
PHONE_FIELD_RE = re.compile(r"Phone:\s*<span>([^<]*)</span>")
EMAIL_FIELD_RE = re.compile(r"Email:\s*<span>(.*?)</span>", re.S)
URL_FIELD_RE = re.compile(r"Url:\s*<span>.*?href=\"([^\"]+)\"", re.S)
CHAPTER_NO_RE = re.compile(r"Chapter Number:\s*</h5>\s*<p>\s*(\d+)\s*</p>", re.S)
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
ZIP_RE = re.compile(r"^\d{5}(-\d{4})?$")

US_COUNTRIES = {"united states", "puerto rico", "guam", "us virgin islands",
                "u.s. virgin islands", "american samoa",
                "northern mariana islands"}
# the state field is a free-text wpsl input: "CO" and "Colorado" both occur
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
    "pennsylvania": "pa", "rhode island": "ri", "south carolina": "sc",
    "south dakota": "sd", "tennessee": "tn", "texas": "tx", "utah": "ut",
    "vermont": "vt", "virginia": "va", "washington": "wa",
    "west virginia": "wv", "wisconsin": "wi", "wyoming": "wy",
    "puerto rico": "pr", "guam": "gu", "northern mariana islands": "mp",
    "american samoa": "as", "virgin islands": "vi", "us virgin islands": "vi",
}
US_STATE_CODES = set(STATE_NAMES.values()) | {"dc"}


def state_code(raw: str) -> str:
    raw = (raw or "").strip().lower()
    if len(raw) == 2:
        return raw if raw in US_STATE_CODES else ""
    return STATE_NAMES.get(raw, "")


def clean_phone(raw: str) -> str | None:
    digits = re.sub(r"\D", "", raw or "")
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    if len(digits) != 10:
        return None
    return f"{digits[:3]}-{digits[3:6]}-{digits[6:]}"


def page_location(page: str) -> dict:
    """The chapter page's embedded wpslMap location object, or {}."""
    m = MAP_RE.search(page)
    if not m:
        return {}
    try:
        obj, _ = json.JSONDecoder().raw_decode(page, m.end())
        locations = obj.get("locations") or []
        return locations[0] if locations else {}
    except (ValueError, TypeError):
        return {}


def main(argv):
    force = "--force" in argv
    places = Places()
    source_id = write_source(
        "compassionatefriends", "chapter-locator",
        kind="directory", publisher="The Compassionate Friends",
        title="TCF chapter locator (wpsl_stores REST API + chapter pages)",
        url=LOCATOR_URL, tier="primary",
    )

    stores, page_no = [], 1
    while page_no <= 10:
        cache = SOURCES / "compassionatefriends" / f"stores-p{page_no}.json"
        batch = json.loads(fetch(API.format(page=page_no), cache,
                                 force=force).read_text())
        stores.extend(batch)
        if len(batch) < 100:
            break
        page_no += 1
    if len(stores) < 300:
        raise SystemExit(f"compassionatefriends: only {len(stores)} stores — "
                         "expected ~437")

    records, skipped, got = [], Counter(), Counter()
    for store in stores:
        name = html.unescape((store.get("title", {}).get("rendered") or "")).strip()
        link = store.get("link") or ""
        if not name or "/chapter/" not in link:
            skipped["no-name-or-link"] += 1
            continue
        page = fetch(link, SOURCES / "compassionatefriends" / "pages" /
                     f"{store['slug']}.html", force=force).read_text(errors="replace")
        loc = page_location(page)
        country = (loc.get("country") or "").strip().lower()
        if country and country not in US_COUNTRIES:
            skipped["non-us"] += 1
            continue
        st = state_code(loc.get("state") or "")
        if not st:
            skipped["no-state"] += 1
            continue

        rec = {
            "_state": st, "_place_slug": "", "_name": name,
            "categories": ["family-support", "peer-support"],
            "parent_org": "us/compassionate-friends",
        }
        addr = {}
        street = (loc.get("address") or "").strip()
        street2 = (loc.get("address2") or "").strip()
        if street:
            addr["street"] = street
            if street2:
                addr["street2"] = street2
        elif street2:
            addr["street"] = street2
        city = (loc.get("city") or "").strip()
        if city:
            addr.update(city=city, state=st)
            zipc = (loc.get("zip") or "").strip()
            if ZIP_RE.match(zipc):
                addr["zip"] = zipc
            rec["address"] = Flow(addr)
            got["address"] += 1
            geoid, _ = places.resolve(st, city)
            if geoid:
                rec["place"] = geoid
                got["place"] += 1
        try:
            rec["geo"] = Flow(lat=round(float(loc["lat"]), 5),
                              lng=round(float(loc["lng"]), 5))
            got["geo"] += 1
        except (KeyError, TypeError, ValueError):
            pass
        phone = clean_phone(PHONE_FIELD_RE.search(page).group(1)
                            if PHONE_FIELD_RE.search(page) else "")
        if phone:
            rec["phone"] = phone
            got["phone"] += 1
        me = EMAIL_FIELD_RE.search(page)
        if me:
            em = EMAIL_RE.search(html.unescape(re.sub(r"<[^>]+>", "", me.group(1))))
            if em:
                rec["email"] = em.group(0)
                got["email"] += 1
        external_ids = Flow(wpsl=str(store["id"]))
        mu = URL_FIELD_RE.search(page)
        if mu:
            url = html.unescape(mu.group(1)).strip()
            if url and not re.match(r"https?://", url, re.I):
                url = "https://" + url
            rec["website"] = url
            external_ids["tcf_chapter_page"] = link
            got["website"] += 1
        else:
            rec["website"] = link
        mn = CHAPTER_NO_RE.search(page)
        if mn:
            external_ids["tcf_chapter"] = mn.group(1)
        rec["external_ids"] = external_ids
        rec["sources"] = [source_id]
        rec["verified"] = Flow(on=today(), method="scrape")
        records.append(rec)

    if skipped:
        print("skipped:", dict(skipped))
    for field in ("address", "place", "geo", "phone", "email", "website"):
        print(f"enriched {got[field]}/{len(records)} chapters with {field}")
    if len(records) < 350:
        raise SystemExit(f"compassionatefriends: only {len(records)} US chapters "
                         "— expected ~430")

    records.append({
        "_state": "us", "_place_slug": "", "_name": "The Compassionate Friends",
        "id": "us/compassionate-friends",
        "categories": ["family-support", "peer-support"],
        "description": "Grief support after the death of a child — local "
                       "chapters hold peer support meetings for bereaved "
                       "parents, siblings, and grandparents. National office "
                       "877-969-0010.",
        "website": "https://www.compassionatefriends.org",
        "phone": "877-969-0010",
        "service_area": Flow(kind="national"),
        "sources": [source_id],
        "verified": Flow(on=today(), method="scrape"),
    })

    replace_records("orgs", source_id, records)


if __name__ == "__main__":
    main(sys.argv[1:])
