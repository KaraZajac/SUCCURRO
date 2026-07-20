"""CenterLink LGBTQ+ community center directory -> org records (lgbtq / lgbtq-center).

The directory (https://web.lgbtqcenters.org/atlas/directory/category/
all-centerlink-members) is a WebLink/MemberClicks "Atlas" Angular SPA. The data
comes from POST https://api-internal.weblinkconnect.com/api/website/v1/listing/search
with JSON body {"PageNumber": N, "PageSize": 20, "CategoryIds": [6], ...}, paged
(~325 listings / 17 pages), authorized by a short-lived Bearer JWT the SPA mints
against weblinkauth.com (client AtlasMemberPortalSpa) — so the endpoint is not
curl-able standalone. Capture is a documented one-shot browser step:

    python3 -m pipeline.centerlink --capture   # needs playwright + chromium

It loads the directory once headless, sniffs the listing/search request (URL,
auth headers, body), replays it for every page inside the same browser context,
and saves sources/centerlink/search-p<N>.json. Normal runs build purely from
that cache.

Data quirks: street addresses are masked ("*") for nearly all listings — only
city/state/zip are published; Latitude/Longitude use "-1" as a null sentinel;
a couple of rows spell the state out ("California") or leave Country blank
(inferred US when the state is a USPS code + 5-digit zip); non-US members
(Canada, Uganda, Australia, Colombia) are excluded.

Usage: python3 -m pipeline.centerlink [--capture]
"""
import json
import re
import sys

from .emit import Places, replace_records, today, write_source
from .util import Flow, SOURCES

DIRECTORY_URL = ("https://web.lgbtqcenters.org/atlas/directory/category/"
                 "all-centerlink-members")
CACHE = SOURCES / "centerlink"

US_STATES = {
    "al", "ak", "az", "ar", "ca", "co", "ct", "de", "dc", "fl", "ga", "hi",
    "id", "il", "in", "ia", "ks", "ky", "la", "me", "md", "ma", "mi", "mn",
    "ms", "mo", "mt", "ne", "nv", "nh", "nj", "nm", "ny", "nc", "nd", "oh",
    "ok", "or", "pa", "pr", "ri", "sc", "sd", "tn", "tx", "ut", "vt", "va",
    "wa", "wv", "wi", "wy", "gu", "vi", "mp", "as",
}
STATE_NAMES = {
    "california": "ca", "illinois": "il", "texas": "tx", "florida": "fl",
    "new york": "ny",  # the few observed / likely spelled-out values
}


def capture():
    """One-shot headless capture of the paginated listing/search XHR."""
    from playwright.sync_api import sync_playwright  # not a pipeline dependency

    CACHE.mkdir(parents=True, exist_ok=True)
    captured = {}

    def on_request(req):
        if "listing/search" in req.url and not captured:
            captured.update(url=req.url, headers=dict(req.headers),
                            post_data=req.post_data)

    with sync_playwright() as p:
        browser = p.chromium.launch()
        ctx = browser.new_context()
        page = ctx.new_page()
        page.on("request", on_request)
        page.goto(DIRECTORY_URL, wait_until="networkidle", timeout=90000)
        page.wait_for_timeout(5000)
        if not captured:
            raise SystemExit("centerlink: listing/search XHR never fired — "
                             "SPA changed?")
        headers = {k: v for k, v in captured["headers"].items()
                   if not k.startswith(":") and k.lower() != "content-length"}
        n_pages, pageno = 99, 1
        while pageno <= n_pages:
            body = json.loads(captured["post_data"])
            body["PageNumber"] = pageno
            resp = ctx.request.post(captured["url"], headers=headers,
                                    data=json.dumps(body))
            d = resp.json()
            n_pages = d.get("TotalPages", 1)
            (CACHE / f"search-p{pageno}.json").write_text(json.dumps(d, indent=1))
            print(f"captured page {pageno}/{n_pages}: {len(d.get('Result', []))} listings")
            pageno += 1
        browser.close()


def us_state(row: dict) -> str | None:
    """USPS code for a US listing, else None (non-US or unlocatable)."""
    st = (row.get("State") or "").strip()
    code = st.lower() if len(st) == 2 else STATE_NAMES.get(st.lower())
    if code not in US_STATES:
        return None
    country = (row.get("Country") or "").strip().lower()
    if country in ("usa", "united states", "us"):
        return code
    if not country and re.fullmatch(r"\d{5}", (row.get("Zip") or "").strip()):
        return code  # blank country but clearly a US address
    return None


def clean_phone(raw: str) -> str | None:
    digits = re.sub(r"\D", "", raw or "")
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    if len(digits) != 10:
        return None
    return f"{digits[:3]}-{digits[3:6]}-{digits[6:]}"


def main(argv):
    if "--capture" in argv:
        capture()

    pages = sorted(CACHE.glob("search-p*.json"),
                   key=lambda p: int(p.stem.split("-p")[1]))
    if not pages:
        raise SystemExit("centerlink: no cached pages under sources/centerlink/ — "
                         "run: python3 -m pipeline.centerlink --capture")
    rows = []
    for path in pages:
        rows.extend(json.loads(path.read_text())["Result"])
    if len(rows) < 250:
        raise SystemExit(f"centerlink: only {len(rows)} listings in cache — "
                         "expected ~325; re-capture?")

    places = Places()
    source_id = write_source(
        "centerlink", "member-directory",
        kind="api-feed", publisher="CenterLink",
        title="CenterLink member directory (Atlas listing/search API)",
        url=DIRECTORY_URL, tier="primary",
    )

    records = []
    for row in rows:
        name = (row.get("DisplayName") or "").strip()
        st = us_state(row)
        if not name or not st:
            continue
        city = (row.get("City") or "").strip()
        if city.isupper():
            city = city.title()
        rec = {
            "_state": st, "_place_slug": "", "_name": name,
            "categories": ["lgbtq", "lgbtq-center"],
        }
        addr = {}
        street = (row.get("Address1") or "").strip()
        if street and street != "*":
            addr["street"] = street
        if city:
            addr.update(city=city, state=st)
            zipc = (row.get("Zip") or "").strip()
            if re.fullmatch(r"\d{5}", zipc):
                ext = (row.get("ZipExt") or "").strip()
                addr["zip"] = f"{zipc}-{ext}" if re.fullmatch(r"\d{4}", ext) else zipc
            rec["address"] = Flow(addr)
            geoid, _ = places.resolve(st, city)
            if geoid:
                rec["place"] = geoid
        try:
            lat, lng = float(row["Latitude"]), float(row["Longitude"])
            if lat != -1 and lng != -1:
                rec["geo"] = Flow(lat=round(lat, 5), lng=round(lng, 5))
        except (KeyError, TypeError, ValueError):
            pass
        website = (row.get("Website") or "").strip()
        if website:
            if not re.match(r"https?://", website, re.I):
                website = "https://" + website
            rec["website"] = website
        phone = clean_phone(row.get("WorkPhone") or row.get("HomeOtherPhone") or "")
        if phone:
            rec["phone"] = phone
        email = (row.get("Email") or "").strip()
        if email:
            rec["email"] = email
        rec["external_ids"] = Flow(weblink_listing=str(row["ListingId"]))
        rec["sources"] = [source_id]
        rec["verified"] = Flow(on=today(), method="api")
        records.append(rec)

    if len(records) < 180:
        raise SystemExit(f"centerlink: only {len(records)} US centers — expected ~300")
    print(f"parsed {len(records)} US centers from {len(rows)} listings")
    replace_records("orgs", source_id, records)


if __name__ == "__main__":
    main(sys.argv[1:])
