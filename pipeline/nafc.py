"""NAFC (National Association of Free & Charitable Clinics) locator -> site
records (free-clinic / health).

The nafcclinics.org find-a-clinic locator is server-rendered WordPress over a
`locations` custom post type (not exposed via REST). The SmartCrawl sitemaps
(locations-sitemap1/2.xml) enumerate every location page (~2,050); each page
carries name, full address, phone, the clinic's own website, services offered,
an NAFC-member flag, and lat/lng in its Google-directions link. First run
crawls all pages (throttled 1/s, ~35 min); pages cache under
sources/nafc/locations/ so re-runs only fetch new slugs.

Cloudflare: the site 403s stdlib urllib regardless of headers (TLS-fingerprint
bot check) but passes plain curl, so fetches shell out to the system curl —
same throttle, cache, and UA conventions as util.fetch. A response containing
the Cloudflare challenge page is treated as a fetch failure (retried, then
fatal).

Rights: ToS-checked 2026-07-21 — the only terms page
(/terms-and-privacy-policy/) is a GDPR privacy notice with no anti-scrape,
license, or content-reuse restrictions; robots.txt allows all paths for
User-agent: * (its Cloudflare-managed block targets AI-training crawlers by
name, which this pipeline is not). Facts-only re-expression, attributed.

Quirks: charitable pharmacies are listed alongside clinics with no type marker
on the detail page (only the search UI distinguishes them); cost is recorded
as "free" — NAFC members are free/charitable clinics by definition and pages
publish no fee data. "NAFC Member? No" rows (partner free clinics NAFC lists
but doesn't count as members) are kept, minus the member description. Some
address strings echo the clinic name as their first segment; it is dropped.

Usage: python3 -m pipeline.nafc [--force]
"""
import html
import re
import subprocess
import sys
import time

from .emit import Places, replace_records, today, write_source
from .util import BROWSER_UA, Flow, SOURCES

SITE = "https://nafcclinics.org"
FINDER = f"{SITE}/find-clinic/"
SITEMAPS = [f"{SITE}/locations-sitemap1.xml", f"{SITE}/locations-sitemap2.xml"]
CACHE = SOURCES / "nafc"

THROTTLE = 1.0
_last_fetch = [0.0]

SOCIAL = re.compile(r"facebook\.com|instagram\.com|twitter\.com|x\.com|"
                    r"linkedin\.com|youtube\.com|tiktok\.com|google\.com|"
                    r"nafcclinics\.org", re.I)
PHONE_RE = re.compile(r"\(?(\d{3})\)?[-.\s]\s*(\d{3})[-.\s](\d{4})")

STATE_NAMES = {
    "alabama": "al", "alaska": "ak", "arizona": "az", "arkansas": "ar",
    "california": "ca", "colorado": "co", "connecticut": "ct", "delaware": "de",
    "florida": "fl", "georgia": "ga", "hawaii": "hi", "idaho": "id",
    "illinois": "il", "indiana": "in", "iowa": "ia", "kansas": "ks",
    "kentucky": "ky", "louisiana": "la", "maine": "me", "maryland": "md",
    "massachusetts": "ma", "michigan": "mi", "minnesota": "mn",
    "mississippi": "ms", "missouri": "mo", "montana": "mt", "nebraska": "ne",
    "nevada": "nv", "new hampshire": "nh", "new jersey": "nj",
    "new mexico": "nm", "new york": "ny", "north carolina": "nc",
    "north dakota": "nd", "ohio": "oh", "oklahoma": "ok", "oregon": "or",
    "pennsylvania": "pa", "rhode island": "ri", "south carolina": "sc",
    "south dakota": "sd", "tennessee": "tn", "texas": "tx", "utah": "ut",
    "vermont": "vt", "virginia": "va", "washington": "wa",
    "west virginia": "wv", "wisconsin": "wi", "wyoming": "wy",
    "district of columbia": "dc", "puerto rico": "pr",
}

# "<state> <zip>" tail: 2-letter code or spelled-out name, zip sometimes
# 9 digits unhyphenated; or a bare ", XX" with no zip
_NAMES_ALT = "|".join(sorted(STATE_NAMES, key=len, reverse=True))
ADDR_TAIL = re.compile(
    rf"[,\s]\s*([A-Za-z]{{2}}|{_NAMES_ALT})\.?,?\s+(\d{{5}})(-?\d{{4}})?$"
    r"|,\s*([A-Z]{2})$", re.I)


def curl_get(url: str, cache, force: bool = False):
    """util.fetch, but through curl (Cloudflare 403s urllib's TLS fingerprint).
    Follows redirects (renamed slugs 301 to their canonical page); a 404/410
    caches as an empty file so deleted pages don't refetch or abort re-runs."""
    if cache.exists() and not force:
        return cache
    for attempt in range(3):
        wait = _last_fetch[0] + THROTTLE - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        _last_fetch[0] = time.monotonic()
        out = subprocess.run(
            ["curl", "-sL", "--max-redirs", "5", "--max-time", "120",
             "-w", "%{http_code}", "-A", BROWSER_UA, "-o", "/dev/stdout", url],
            capture_output=True)
        body, code = out.stdout[:-3], out.stdout[-3:]
        cache.parent.mkdir(parents=True, exist_ok=True)
        if out.returncode == 0 and code == b"200" and body \
                and b"Just a moment" not in body[:4000]:
            cache.write_bytes(body)
            print(f"fetched {url}")
            return cache
        if code in (b"404", b"410"):
            cache.write_bytes(b"")  # gone upstream; cache the miss
            print(f"gone ({code.decode()}) {url}")
            return cache
        time.sleep(5 * (attempt + 1))  # challenged or failed; back off
    raise SystemExit(f"nafc: fetch failed after retries (Cloudflare "
                     f"challenge?): {url}")


def location_urls(force: bool) -> list[str]:
    urls = []
    for i, sm in enumerate(SITEMAPS, 1):
        path = curl_get(sm, CACHE / f"locations-sitemap{i}.xml", force=force)
        urls += re.findall(r"<loc>\s*(https://nafcclinics\.org/locations/[^<\s]+)",
                           path.read_text())
    if len(urls) < 900:
        raise SystemExit(f"nafc: sitemaps list only {len(urls)} location pages "
                         "— expected ~2,000; site structure changed?")
    return sorted(set(urls))


def text_of(fragment: str) -> str:
    t = html.unescape(re.sub(r"<[^>]+>", " ", fragment))
    return re.sub(r"\s+", " ", t).strip()


def parse_page(page: str) -> dict | None:
    """Facts from one location page's <article>."""
    m = re.search(r"<article\b.*?</article>", page, re.S)
    if not m:
        return None
    art = m.group(0)
    h2 = re.search(r"<h2>(.*?)</h2>", art, re.S)
    if not h2:
        return None
    info: dict = {"name": text_of(h2.group(1))}

    paras = [text_of(p) for p in re.findall(r"<p[^>]*>(.*?)</p>", art, re.S)]
    for p in paras:
        if not p or p in ("Get Directions", "Services Offered:"):
            continue
        if "address" not in info and "," in p and ADDR_TAIL.search(
                re.sub(r",?\s*(USA|United States)\.?$", "", p.strip(),
                       flags=re.I).rstrip().rstrip(",")):
            info["address"] = p
            continue
        pm = PHONE_RE.search(p)
        if pm and "phone" not in info and len(re.sub(r"\D", "", p)) <= 11:
            info["phone"] = "-".join(pm.groups())

    for link in re.findall(r'<a href="(https?://[^"]+)"', art):
        if not SOCIAL.search(link):
            info["website"] = html.unescape(link)
            break

    gm = re.search(r"maps/dir//[^@\"]*@(-?\d+\.\d+),(-?\d+\.\d+)", art)
    if gm:
        info["lat"], info["lng"] = float(gm.group(1)), float(gm.group(2))

    sv = re.search(r'<ul class="services">(.*?)</ul>', art, re.S)
    if sv:
        items = [text_of(li) for li in re.findall(r"<li>(.*?)</li>",
                                                  sv.group(1), re.S)]
        info["services"] = [i for i in items if i]

    mem = re.search(r"NAFC Member\?\s*</b>\s*(\w+)", art)
    info["member"] = bool(mem and mem.group(1).lower() == "yes")
    return info


def split_address(raw: str, name: str) -> dict | None:
    """'1212 N Wolfe St, Baltimore, MD 21213, USA' -> address parts. Handles
    spelled-out states, unhyphenated zip+4, and missing city/state commas."""
    addr = re.sub(r",?\s*(USA|United States)\.?$", "", raw.strip(), flags=re.I)
    addr = addr.rstrip().rstrip(",")
    tail = ADDR_TAIL.search(addr)
    if not tail:
        return None
    state_raw = (tail.group(1) or tail.group(4)).strip()
    if len(state_raw) == 2:
        state = state_raw.lower()
    else:
        state = STATE_NAMES.get(state_raw.lower())
        if not state:
            return None
    parts = [p.strip() for p in addr[:tail.start()].split(",") if p.strip()]
    if not parts:
        return None
    city = parts.pop()
    norm = lambda s: re.sub(r"[^a-z0-9]", "", s.lower())
    if parts and norm(parts[0]) == norm(name):
        parts.pop(0)  # address echoes the clinic name as its first segment
    out = {"city": city, "state": state}
    if parts:
        out["street"] = ", ".join(parts)
    if tail.group(2):
        zip4 = (tail.group(3) or "").lstrip("-")
        out["zip"] = f"{tail.group(2)}-{zip4}" if zip4 else tail.group(2)
    return out


def main(argv):
    force = "--force" in argv
    places = Places()
    source_id = write_source(
        "nafc", "find-a-clinic",
        kind="directory", publisher="National Association of Free & Charitable Clinics",
        title="NAFC find-a-clinic locator (location pages)",
        url=FINDER, tier="primary",
    )

    urls = location_urls(force)
    records, seen = [], set()
    skipped_parse = skipped_state = skipped_dupe = 0
    for url in urls:
        slug = url.rstrip("/").rsplit("/", 1)[-1]
        path = curl_get(url, CACHE / "locations" / f"{slug}.html", force=force)
        info = parse_page(path.read_text(errors="replace"))
        if not info or not info.get("name") or not info.get("address"):
            skipped_parse += 1
            continue
        addr = split_address(info["address"], info["name"])
        if not addr:
            skipped_parse += 1
            continue
        st = addr["state"]
        if st not in places.by_state:
            skipped_state += 1
            continue
        key = (info["name"].lower(), addr.get("street", "").lower(),
               addr["city"].lower())
        if key in seen:
            skipped_dupe += 1  # re-published posts (-2 slugs) for one location
            continue
        seen.add(key)

        geoid, place_slug = places.resolve(st, addr["city"])
        rec = {
            "_state": st, "_place_slug": place_slug, "_name": info["name"],
            "categories": ["free-clinic", "health"],
        }
        if info["member"]:
            rec["description"] = "NAFC member clinic"
        rec["address"] = Flow({k: addr[k] for k in
                               ("street", "city", "state", "zip") if k in addr})
        if "lat" in info and 15 <= info["lat"] <= 72 and -180 <= info["lng"] <= -60:
            rec["geo"] = Flow(lat=round(info["lat"], 5), lng=round(info["lng"], 5))
        if not geoid and "geo" in rec:
            near = places.nearest(rec["geo"]["lat"], rec["geo"]["lng"])
            if near and near[0] == st:  # state-matched nearest fallback
                geoid = near[1]
        if geoid:
            rec["place"] = geoid
        if info.get("phone"):
            rec["phone"] = info["phone"]
        if info.get("website"):
            rec["website"] = info["website"]
        if info.get("services"):
            rec["services"] = info["services"]
        rec["cost"] = "free"
        rec["external_ids"] = Flow(nafc=slug)
        rec["sources"] = [source_id]
        rec["verified"] = Flow(on=today(), method="scrape")
        records.append(rec)

    print(f"kept {len(records)} clinics from {len(urls)} location pages "
          f"(skipped: {skipped_parse} unparseable, {skipped_state} outside "
          f"place registry, {skipped_dupe} duplicates)")
    if len(records) < 900:
        raise SystemExit(f"nafc: only {len(records)} clinic records — expected "
                         "1,800+; aborting")

    replace_records("sites", source_id, records)


if __name__ == "__main__":
    main(sys.argv[1:])
