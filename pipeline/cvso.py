"""County Veteran Service Officer directories -> org records (veterans).

No national CVSO roster exists; state veterans agencies publish (or
don't) a county-office directory on their own sites. Registry-structured
(STATES, like dvcoalitions.COALITIONS): each state with a parseable
county directory gets its own parser and its own per-state source record
under the shared "cvso/" prefix (data/sources/cvso/<st>.yaml, id
cvso/<st>), so each state's re-run replaces exactly its own records.
Pages/feeds cache under sources/cvso/.

2026-07 all-state survey summary (see module registry for the built
set): built 22 states (the LA/ND/NY multi-page crawls deferred by the
survey are now built, and the AR/FL/NC PDFs deferred as multi-column
are parsed via blank-gutter column splitting below); JS/blocked with no
recoverable feed: CA, KS, MA, NH, VA (MA's monthly VSO CSV re-probed
2026-07: mass.gov's WAF 403s python and curl even with browser
headers — client fingerprinting, not UA); PDF-only left unbuilt: TX
(the FIND-A-VSO roster is county->website only; recovering phones would
mean crawling ~250 county sites — skipped); state-office systems only
(no county roster): AK, AZ, CT, DE, GA, HI, ID, KY, MD, ME, MO*, MT,
NM, NV, OK, RI, UT, VT, WA, WV, WY (*MO's ArcGIS feed is state-run
offices; MI similar). NC's county roster is no longer on the live DMVA
site (the 2026 refresh points veterans at county websites); it is
parsed from the DMVA Resource Guide 2024-25 PDF via the Internet
Archive (archive_url on the source record).

FACTS-ONLY: the office is the record, not the person — officer personal
names and personal emails are never recorded; phone is the published
office line, email only when clearly organizational (veterans@...,
cvso@..., office inboxes).

Usage: python3 -m pipeline.cvso [state ...] [--force]
"""
import html
import json
import re
import subprocess
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.parse import quote_plus
from urllib.request import Request, urlopen

from .emit import replace_records, today, write_source
from .util import BROWSER_UA, Flow, SOURCES, UA, fetch, slugify

PHONE_RE = re.compile(r"\(?\b(\d{3})\)?[-. ]\s*(\d{3})[-. ](\d{4})\b")

# emails whose local part is organizational, not a person
ORG_EMAIL_RE = re.compile(
    r"^(veteran|vso|cvso|vet|info|office|contact|admin|va|ask)[\w.-]*@", re.I)

EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+(\.[\w-]+)+")


def strip_tags(fragment: str) -> str:
    fragment = re.sub(r"<br\s*/?>", "\n", fragment)
    return html.unescape(re.sub(r"<[^>]+>", " ", fragment))


def squash(text: str) -> str:
    return " ".join(text.split())


def phone_fmt(text: str) -> str | None:
    """First US phone in `text` as AAA-BBB-CCCC (tel: hrefs or display)."""
    digits = re.sub(r"\D", "", text or "")
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    if len(digits) == 10:
        return f"{digits[:3]}-{digits[3:6]}-{digits[6:]}"
    m = PHONE_RE.search(text or "")
    return f"{m.group(1)}-{m.group(2)}-{m.group(3)}" if m else None


def org_email(text: str) -> str | None:
    """First clearly-organizational email in `text`; personal-looking
    addresses (jane.doe@, jdoe@) are dropped — facts-only policy."""
    for m in EMAIL_RE.finditer(text or ""):
        if ORG_EMAIL_RE.match(m.group(0)) and \
                not re.match(r"^\w+\.\w+@", m.group(0)):
            return m.group(0).lower()
    return None


def city_of(text: str, st: str) -> str | None:
    """City from an address fragment like '..., West Union, OH 45693'."""
    m = re.search(r"([A-Za-z][A-Za-z .'-]+?),?\s+" + st.upper()
                  + r"\.?,?\s+\d{5}", text or "")
    if not m:
        return None
    city = m.group(1).strip(" ,.")
    # drop a leading street fragment that ran into the city name
    city = re.sub(r"^.*\d\S*\s+", "", city).strip(" ,.")
    city = re.sub(r"^.*\b(Street|St|Ave|Avenue|Road|Rd|Drive|Dr|Blvd|"
                  r"Boulevard|Lane|Ln|Hwy|Highway|Square|Sq|Court|Ct|Suite|"
                  r"Ste|Floor|Room|Box)\.?\s+", "", city).strip(" ,.")
    return city or None


def record(st: str, counties, source_id: str, *, name: str = "",
           desc: str = "", city: str | None = None, phone: str | None = None,
           email: str | None = None, website: str | None = None) -> dict:
    """One county veteran service office. `counties` is a bare county
    name or a list (multi-county offices get no service_area, the
    counties named in the description instead)."""
    counties = [counties] if isinstance(counties, str) else counties
    primary = counties[0]
    name = name or f"{primary} County Veterans Service Office"
    if not desc:
        served = (f"{primary} County" if len(counties) == 1 else
                  " and ".join(", ".join(counties).rsplit(", ", 1))
                  + " counties")
        desc = (f"County veteran service office serving {served}, "
                f"{st.upper()}. Assists veterans and their families with "
                "VA benefit claims and local veteran services.")
    rec = {"_state": st, "_place_slug": "", "_name": squash(name),
           "categories": ["veterans"], "description": squash(desc)}
    if city:
        rec["address"] = Flow(city=squash(city), state=st)
    if phone:
        rec["phone"] = phone
    if email:
        rec["email"] = email
    if website:
        rec["website"] = html.unescape(website).strip()
    if len(counties) == 1:
        rec["service_area"] = Flow(kind="county", name=primary, state=st)
    rec["sources"] = [source_id]
    rec["verified"] = Flow(on=today(), method="scrape")
    return rec


# --- AL: va.alabama.gov service-officer map --------------------------------
# One igm-map-content div per county FIPS; offices serving several
# counties repeat per county ("Counties Served" row) — merged by name.

def parse_al(page: str, source_id: str) -> list[dict]:
    seen, records = set(), []
    for block in re.split(
            r'<div data-original-id="[^"]*"[^>]*class="igm-map-content"',
            page)[1:]:
        name_m = re.search(r"<h2>(.*?)</h2>", block, re.S)
        if not name_m:
            continue
        name = squash(strip_tags(name_m.group(1)))
        if name.lower() in seen:
            continue
        seen.add(name.lower())

        def row(label):
            m = re.search(label + r":?</b></td>\s*<td>(.*?)</td>", block, re.S)
            return squash(strip_tags(m.group(1))) if m else ""

        served = row("Counties Served")
        counties = [c.strip() for c in re.split(r",|\band\b", served)
                    if c.strip()]
        if not counties:  # fall back to the office name
            cm = re.match(r"(.*?) County", name)
            counties = [cm.group(1)] if cm else []
        if not counties:
            print(f"al: no county for {name!r} — skipped")
            continue
        records.append(record("al", counties, source_id, name=name,
                              city=row("City") or None,
                              phone=phone_fmt(row("Tel"))))
    return records


# --- CO: vets.colorado.gov accordion ---------------------------------------
# <dl class="ckeditor-accordion"> pairs: <dt>County</dt><dd> with <h3>
# Phone sections; officer names/emails deliberately not parsed.

def parse_co(page: str, source_id: str) -> list[dict]:
    records = []
    for dt, dd in re.findall(r"<dt>(.*?)</dt>\s*<dd>(.*?)</dd>", page, re.S):
        county = squash(strip_tags(dt))
        if not county or "report" in county.lower():
            continue
        text = strip_tags(dd)
        phone_m = (re.search(r"Phone[^<]*</h3>\s*<p[^>]*>(.*?)</p>", dd, re.S)
                   or re.search(r"Phone:?\s*([\d() .-]{10,})", text))
        phone = phone_fmt(strip_tags(phone_m.group(1))) if phone_m else None
        if not phone:
            phone = phone_fmt(re.sub(r"Fax[^<]*</h3>\s*<p[^>]*>.*?</p>", "",
                                     dd, flags=re.S | re.I))
        records.append(record("co", county, source_id,
                              city=city_of(text, "co"), phone=phone,
                              email=org_email(text)))
    return records


# --- IA: dva.iowa.gov service map listing ----------------------------------
# Drupal view; each item is a location-type div followed by the linked
# title, structured address, and county website. Only the items typed
# "County Veterans Service Office" are county offices (the same view
# also lists state/federal locations). No phone in the listing.

def parse_ia(page: str, source_id: str) -> list[dict]:
    records = []
    chunks = re.split(r'class="location-type visual-title__meta"\s*>', page)
    for chunk in chunks[1:]:
        kind = chunk[:chunk.find("<")].strip()
        if kind != "County Veterans Service Office":
            continue
        name_m = re.search(r'class="section-heading"[^>]*>\s*<span>(.*?)</span>',
                           chunk, re.S)
        if not name_m:
            continue
        name = squash(strip_tags(name_m.group(1)))
        # upstream typo tolerance: "MahaskaCounty Veterans Affairs"
        cm = re.match(r"(.+?)\s*County\b", name)
        if not cm:
            print(f"ia: unrecognized county in {name!r} — skipped")
            continue
        city_m = re.search(r'"locality">([^<]*)', chunk)
        web_m = re.search(r'field--name-field-website.*?href="([^"]+)"',
                          chunk, re.S)
        records.append(record(
            "ia", cm.group(1), source_id, name=name,
            city=squash(city_m.group(1)) if city_m else None,
            website=web_m.group(1) if web_m else None))
    return records


# --- IL: IDVA county-list content-fragment JSON ----------------------------
# State-run IDVA service offices stationed per county (Illinois's
# county Veterans Assistance Commissions publish no roster).

def parse_il(text: str, source_id: str) -> list[dict]:
    records = []
    for item in json.loads(text).get("listItems", []):
        if item.get("isActive") != "true":
            continue
        county = (item.get("county") or "").strip()
        raw = (item.get("locationName") or "").strip()
        if not county or not raw:
            continue
        closed = "temporarily closed" in raw.lower()
        name = squash(re.sub(r"\s*-?\s*\*+\s*Temporarily Closed\s*\*+", "",
                             raw, flags=re.I))
        desc = (f"Illinois Department of Veterans' Affairs service office "
                f"serving {county} County, IL. Assists veterans and their "
                "families with VA benefit claims.")
        if closed:
            desc += " Listed as temporarily closed in the directory."
        records.append(record("il", county, source_id, name=name, desc=desc,
                              city=(item.get("city") or "").strip() or None,
                              phone=phone_fmt(item.get("officeNumber"))))
    return records


# --- IN: in.gov/dva cvso-locate accordion ----------------------------------
# One county_<slug> div per county; table cells hold officer + address
# and hours + phone/fax/website. Table shapes vary; parsed leniently.

def parse_in(page: str, source_id: str) -> list[dict]:
    records = []
    parts = re.split(r'<div class="county_([a-z_]+) county-intro-content">',
                     page)
    for slug, block in zip(parts[1::2], parts[2::2]):
        county = slug.replace("_", " ").title()
        text = strip_tags(block)
        phone_m = re.search(r"Office:?\s*([\d() .-]{10,})", text)
        phone = phone_fmt(phone_m.group(1)) if phone_m else None
        if not phone:
            fax_free = re.sub(r"FAX:?\s*[\d() .-]{10,}", "", text, flags=re.I)
            phone = phone_fmt(fax_free)
        web_m = re.search(r'Website:.{0,40}?<a href="(https?://[^"]+)"',
                          block, re.S)
        records.append(record("in", county, source_id,
                              city=city_of(text, "in"), phone=phone,
                              email=org_email(text),
                              website=web_m.group(1) if web_m else None))
    return records


# pages of a multi-page crawl are joined on this sentinel for the parser
PAGE_BREAK = "\n<!--cvso-page-break-->\n"


# --- LA: vetaffairs.la.gov locations (parish service offices) --------------
# WordPress locations CPT: a paginated /locations index links one page per
# parish office (plus HQ, veterans homes, and cemeteries — skipped). Detail
# pages carry a segmented <address> and a class="contact phone" tel link
# (the fax sits in a "contact fax" div, the footer holds the LDVA line —
# neither is parsed). Parenthetical variants ((East Bank), (Itinerant
# Point)) are distinct service points and kept as separate records.

LA_TITLE_RE = re.compile(r"<title>\s*([^|<]+?)\s*[|<]")


def fetch_la(url: str, force: bool) -> str:
    first = fetch(url, SOURCES / "cvso" / "la-index.html",
                  force=force).read_text(errors="replace")
    indexes = [first]
    last = max((int(n) for n in re.findall(
        r'href="[^"]*/locations/page/(\d+)', first)), default=1)
    for p in range(2, last + 1):
        indexes.append(fetch(f"{url}/page/{p}",
                             SOURCES / "cvso" / f"la-index-p{p}.html",
                             force=force).read_text(errors="replace"))
    slugs = sorted(set(re.findall(
        r'href="https://vetaffairs\.la\.gov/locations/([a-z0-9-]+)/?"',
        "".join(indexes))))
    if len(slugs) < 70:
        raise SystemExit(f"la: only {len(slugs)} location links — "
                         "index layout changed")
    parts = []
    for slug in slugs:
        parts.append(fetch(f"https://vetaffairs.la.gov/locations/{slug}",
                           SOURCES / "cvso" / f"la-{slug}.html",
                           force=force).read_text(errors="replace"))
    return PAGE_BREAK.join(parts)


def parse_la(pages: str, source_id: str) -> list[dict]:
    records, skipped = [], []
    for chunk in pages.split(PAGE_BREAK):
        title_m = LA_TITLE_RE.search(chunk)
        if not title_m:
            continue
        title = squash(html.unescape(title_m.group(1)))
        if "PARISH" not in title.upper():
            skipped.append(title.title())  # HQ, veterans homes, cemeteries
            continue
        m = re.match(r"(.+?\bPARISH)\s*(\(.+\))?$", title, re.I)
        parish_part = m.group(1).title().replace("Lasalle", "LaSalle")
        variant = m.group(2).title() if m.group(2) else ""
        name = parish_part + " Veteran Service Office" + \
            (f" {variant}" if variant else "")
        base = parish_part[:-len(" Parish")]
        counties = (["East Feliciana", "West Feliciana"]
                    if base == "East/West Feliciana" else [base])
        served = (f"{counties[0]} Parish" if len(counties) == 1 else
                  " and ".join(f"{c} Parish" for c in counties))
        desc = (f"Parish veteran service office serving {served}, LA. "
                "Assists veterans and their families with VA benefit "
                "claims and local veteran services.")
        if "Itinerant" in variant:
            desc += " Itinerant service point of the parish office."
        city_m = re.search(r'segment-city">([^<]+)</span>', chunk)
        phone_m = re.search(r'class="contact phone">([^<]+)<', chunk)
        records.append(record(
            "la", counties, source_id, name=name, desc=desc,
            city=squash(html.unescape(city_m.group(1))).strip(" ,")
            if city_m else None,
            phone=phone_fmt(phone_m.group(1)) if phone_m else None))
    if skipped:
        print(f"la: {len(skipped)} non-parish locations skipped: "
              f"{', '.join(sorted(skipped))}")
    return records


# --- ND: veterans.nd.gov per-county service-officer pages ------------------
# Drupal: the find-a-service-officer page links /service-officers/county/
# <slug>; each county page holds office blocks (views-field-title h2 +
# organization-address + Office Phone) and separate staff hero cards
# (personal names/emails — never parsed). Counties without their own
# staffed office (e.g. Billings) carry a stub block pointing at the
# serving county's office, whose contact details are borrowed with a
# "served through" note.

ND_INDEX = "https://www.veterans.nd.gov/about/find-a-service-officer"


def fetch_nd(url: str, force: bool) -> str:
    index = fetch(url, SOURCES / "cvso" / "nd.html",
                  force=force).read_text(errors="replace")
    slugs = sorted(set(re.findall(
        r'href="/service-officers/county/([a-z0-9-]+)"', index)))
    if len(slugs) < 50:
        raise SystemExit(f"nd: only {len(slugs)} county links — "
                         "index layout changed")
    parts = []
    for slug in slugs:
        parts.append(fetch(
            f"https://www.veterans.nd.gov/service-officers/county/{slug}",
            SOURCES / "cvso" / f"nd-{slug}.html",
            force=force).read_text(errors="replace"))
    return PAGE_BREAK.join(parts)


def _nd_office(block: str) -> dict:
    name_m = re.search(r">([^<]+)</a></h2>", block)
    addr_m = re.search(
        r"field-organization-address.*?field-content\">(.*?)</div>",
        block, re.S)
    phone_m = re.search(r"Office Phone:</strong>\s*([^<]+)", block)
    return {
        "name": squash(strip_tags(name_m.group(1))) if name_m else "",
        "city": city_of(strip_tags(addr_m.group(1)), "nd")
        if addr_m else None,
        "phone": phone_fmt(phone_m.group(1)) if phone_m else None,
    }


def parse_nd(pages: str, source_id: str) -> list[dict]:
    records = []
    for chunk in pages.split(PAGE_BREAK):
        title_m = re.search(r"<title>\s*([^|<]+?)\s*[|<]", chunk)
        if not title_m:
            continue
        county = squash(html.unescape(title_m.group(1)))
        offices = [_nd_office(b) for b in
                   chunk.split('views-field views-field-title')[1:]]
        offices = [o for o in offices if o["name"]]
        if not offices:
            print(f"nd: no office block on {county} page — skipped")
            continue
        own = next((o for o in offices
                    if o["name"].lower().startswith(county.lower())), None)
        serving = next((o for o in offices if o["phone"]), None)
        name = (own or {}).get("name") or \
            f"{county} County Veterans Service Office"
        desc = ""
        if (not own or not own["phone"]) and serving and \
                serving["name"] != name:
            # unstaffed county: record keeps the county office identity,
            # contact details point at the office that serves it
            desc = (f"County veteran service office for {county} County, "
                    f"ND. Served through the {serving['name']}. Assists "
                    "veterans and their families with VA benefit claims "
                    "and local veteran services.")
            own = serving
        own = own or offices[0]
        records.append(record("nd", county, source_id, name=name, desc=desc,
                              city=own["city"], phone=own["phone"]))
    return records


# --- NY: veterans.ny.gov office-locations (county agencies) ----------------
# Drupal listing paginated ?page=0..; /location/<slug> details. Only the
# county veterans service agency pages are taken — the same listing also
# holds NYS DVS field offices, NYC DVS borough offices, and VA facilities.
# The site-header hotline and 988 tel links are skipped; the office phone
# is the article's class="phone-number" link.

NY_URL = "https://veterans.ny.gov/office-locations"
NY_COUNTY_SLUG_RE = re.compile(r"county.*veterans?.*(?:service|services).*agency")


def fetch_ny(url: str, force: bool) -> str:
    slugs: set[str] = set()
    for p in range(0, 30):
        page = fetch(f"{url}?page={p}",
                     SOURCES / "cvso" / f"ny-index-p{p}.html",
                     force=force).read_text(errors="replace")
        found = set(re.findall(r'href="/location/([a-z0-9-]+)"', page))
        if not found - slugs:
            break
        slugs |= found
    else:
        raise SystemExit("ny: still paginating after 30 index pages")
    wanted = sorted(s for s in slugs if NY_COUNTY_SLUG_RE.search(s))
    if len(wanted) < 50:
        raise SystemExit(f"ny: only {len(wanted)} county agency links — "
                         "listing layout changed")
    parts = []
    for slug in wanted:
        parts.append(fetch(f"https://veterans.ny.gov/location/{slug}",
                           SOURCES / "cvso" / f"ny-{slug}.html",
                           force=force).read_text(errors="replace"))
    return PAGE_BREAK.join(parts)


def parse_ny(pages: str, source_id: str) -> list[dict]:
    records = []
    for chunk in pages.split(PAGE_BREAK):
        title_m = re.search(r"<title>\s*([^|<]+?)\s*[|<]", chunk)
        if not title_m:
            continue
        name = squash(html.unescape(title_m.group(1))).replace(" (NY)", "")
        counties = [squash(c) for c in
                    re.findall(r'location-counties">([^<]+)<', chunk)]
        counties = [c for c in counties if c]
        if not counties:
            cm = re.match(r"(.+?) County", name)
            if not cm:
                print(f"ny: no county on {name!r} page — skipped")
                continue
            counties = [cm.group(1)]
        city_m = re.search(r'"locality">([^<]+)<', chunk)
        phone_m = re.search(r'href="tel:([^"]+)" class="phone-number"',
                            chunk)
        served = (f"{counties[0]} County" if len(counties) == 1 else
                  " and ".join(", ".join(counties).rsplit(", ", 1))
                  + " counties")
        desc = (f"County veterans service agency serving {served}, NY. "
                "Assists veterans and their families with VA benefit "
                "claims and local veteran services.")
        records.append(record(
            "ny", counties, source_id, name=name, desc=desc,
            city=squash(html.unescape(city_m.group(1))).strip(" , ")
            or None if city_m else None,
            phone=phone_fmt(phone_m.group(1)) if phone_m else None))
    return records


# --- MN: MACVSO find-a-cvso (per-county GET) -------------------------------
# The MDVA site points to the county VSO association's lookup; a plain
# GET ?county=X+County returns server-rendered person cards — the first
# card per county carries the office phone and (organizational) inbox.

MN_URL = "https://www.macvso.org/find-a-cvso.html"


def fetch_mn(url: str, force: bool) -> str:
    base = fetch(url, SOURCES / "cvso" / "mn.html",
                 force=force).read_text(errors="replace")
    counties = sorted(set(re.findall(
        r'<option value="([^"]+ County)"', base)))
    if len(counties) < 80:
        raise SystemExit(f"mn: only {len(counties)} county options — "
                         "layout changed")
    parts = []
    for county in counties:
        cache = SOURCES / "cvso" / f"mn-{slugify(county)}.html"
        parts.append(fetch(f"{url}?county={quote_plus(county)}", cache,
                           force=force).read_text(errors="replace"))
    return "\n".join(parts)


def parse_mn(pages: str, source_id: str) -> list[dict]:
    by_county: dict[str, dict] = {}
    for m in re.finditer(
            r'class="card__office"><a[^>]*>([^<]+ County)</a>(.*?)'
            r'(?=class="card__office"|cvsoSearch__resultsHeading|$)',
            pages, re.S):
        county = m.group(1).replace(" County", "").strip()
        if county in by_county:
            continue
        body = m.group(2)
        tel_m = re.search(r'itemprop="telephone">([^<]+)', body)
        mail_m = re.search(r'href="mailto:([^"]+)"', body)
        by_county[county] = record(
            "mn", county, source_id,
            phone=phone_fmt(tel_m.group(1)) if tel_m else None,
            email=org_email(mail_m.group(1)) if mail_m else None)
    return list(by_county.values())


# --- MS: msva.ms.gov serviceofficers ---------------------------------------
# Squarespace blocks: <h3>X COUNTY</h3> then address / Office: phone.

def parse_ms(page: str, source_id: str) -> list[dict]:
    records = []
    parts = re.split(r"<h3[^>]*>(.*?)</h3>", page)
    for head, body in zip(parts[1::2], parts[2::2]):
        title = squash(strip_tags(head))
        if not title.upper().endswith("COUNTY"):
            continue
        county = title[:-len("COUNTY")].strip().title()
        body = body[:body.find("<h3")] if "<h3" in body else body
        text = strip_tags(body[:2000])
        phone_m = re.search(r"Office:?\s*([\d() .-]{10,})", text)
        records.append(record(
            "ms", county, source_id, city=city_of(text, "ms"),
            phone=phone_fmt(phone_m.group(1)) if phone_m else phone_fmt(text),
            email=org_email(text)))
    return records


# --- NE: veterans.nebraska.gov/cvso ----------------------------------------
# <h3>X County</h3> then staff <li> rows and an office block; the page
# also embeds an SVG county map — segments are cut at the next <h3>.

def parse_ne(page: str, source_id: str) -> list[dict]:
    records = []
    heads = list(re.finditer(r"<h3>([^<]+ County)</h3>", page))
    for i, hm in enumerate(heads):
        county = hm.group(1).replace(" County", "").strip()
        seg = page[hm.end(): heads[i + 1].start() if i + 1 < len(heads)
                   else len(page)]
        tel_m = re.search(r'href="tel:([^"]+)"', seg)
        email = None
        for mm in re.finditer(r'href="mailto:([^"]+)"', seg):
            email = org_email(mm.group(1))
            if email:
                break
        mail_m = re.search(r"Mailing Address:.{0,20}</span>(.*?)</div>",
                           seg, re.S)
        city = city_of(strip_tags(mail_m.group(1)), "ne") if mail_m else None
        records.append(record("ne", county, source_id, city=city,
                              phone=phone_fmt(tel_m.group(1)) if tel_m
                              else None, email=email))
    return records


# --- NJ: nj.gov/dva VSO offices --------------------------------------------
# Bootstrap cards; county cards only (the Bordentown/Newark/East Orange
# city and liaison offices are skipped). State-DVA-run offices.

def parse_nj(page: str, source_id: str) -> list[dict]:
    records, skipped = [], []
    cards = re.split(r"<div class='card-header", page)
    for card in cards[1:]:
        head_m = re.search(r"<span[^>]*>([^<]+)</span>", card)
        if not head_m:
            continue
        title = squash(head_m.group(1))
        if not title.endswith(" County"):
            skipped.append(title)
            continue
        county = title[:-len(" County")]
        phone_m = re.search(r"Phone:?\s*([\d() ./-]{10,})", card)
        loc_m = re.search(r"<h5>Location</h5>\s*<p>(.*?)</p>", card, re.S)
        city = city_of(strip_tags(loc_m.group(1)), "nj") if loc_m else None
        desc = (f"New Jersey DMAVA veteran service office serving {county} "
                f"County, NJ. Assists veterans and their families with VA "
                "benefit claims.")
        records.append(record(
            "nj", county, source_id, desc=desc, city=city,
            phone=phone_fmt(phone_m.group(1)) if phone_m else None))
    if skipped:
        print(f"nj: skipped non-county offices: {', '.join(skipped)}")
    return records


# --- OH: dvs.ohio.gov find-a-cvso (embedded JSON) --------------------------
# Next.js flight data: the LocationsMap items array ships inside a
# self.__next_f.push() string with escaped quotes.

def parse_oh(page: str, source_id: str) -> list[dict]:
    text = page.replace('\\"', '"')
    items = []
    for m in re.finditer(r'\{[^{}]*"locationName"[^{}]*\}', text):
        try:
            items.append(json.loads(m.group(0)))
        except json.JSONDecodeError:
            print(f"oh: unparseable item blob {m.group(0)[:80]!r} — skipped")
    if len(items) < 80:
        raise SystemExit(f"oh: only {len(items)} items — expected 88")
    records = []
    for item in items:
        name = squash(item.get("locationName") or "")
        cm = re.match(r"(.*?) County", name)
        if not cm:
            print(f"oh: unrecognized county in {name!r} — skipped")
            continue
        records.append(record(
            "oh", cm.group(1), source_id, name=name,
            city=city_of(item.get("address") or "", "oh"),
            phone=phone_fmt(item.get("phone")),
            email=org_email(item.get("email")),
            website=(item.get("website") or "").strip() or None))
    return records


# --- OR: ODVA SharePoint locations list (REST) -----------------------------
# Anonymous list API; "Veteran Services Office" rows are the county VSO
# offices (the list also holds tribal VSOs and other location types).

OR_API = ("https://www.oregon.gov/odva/Services/_api/web/lists/"
          "getbytitle('Locations%20Database')/items?$top=500")


def fetch_or(url: str, force: bool) -> str:
    cache = SOURCES / "cvso" / "or.json"
    if cache.exists() and not force:
        return cache.read_text()
    time.sleep(1.0)
    req = Request(OR_API, headers={
        "User-Agent": UA, "Accept": "application/json;odata=nometadata"})
    try:
        with urlopen(req, timeout=120) as resp:
            body = resp.read()
    except (HTTPError, URLError, TimeoutError) as e:
        raise SystemExit(f"or: list API failed ({e})")
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_bytes(body)
    print("fetched or.json")
    return body.decode(errors="replace")


def parse_or(text: str, source_id: str) -> list[dict]:
    records = []
    for item in json.loads(text).get("value", []):
        if item.get("Location_x0020_Type") != "Veteran Services Office":
            continue
        county = (item.get("County") or "").strip()
        name = squash(item.get("Title") or "")
        if not county or not name:
            continue
        city = (item.get("City") or "").split(",")[0].strip() or None
        records.append(record(
            "or", county, source_id, name=name, city=city,
            phone=phone_fmt(item.get("Phone_x0020_1")),
            email=org_email(item.get("Email")),
            website=(item.get("Website") or "").strip() or None))
    return records


# --- PA: DMVA county directors PDF (MA-VA 400) -----------------------------
# Clean pdftotext -layout table: main rows carry "<County>  County
# Websites?  <Director>  <City, PA zip>  phones  email"; street lines and
# overflow emails print on the lines between main rows.

PA_URL = ("https://www.pa.gov/content/dam/copapwp-pagov/en/dmva/documents/"
          "veteransaffairs/documents/"
          "ma-va%20400%20county%20directors%2007.02.2026.pdf")
PA_MAIN_RE = re.compile(r"^([A-Za-z]+)\s{2,}County Website")


def fetch_pa(url: str, force: bool) -> str:
    pdf = fetch(url, SOURCES / "cvso" / "pa.pdf", force=force)
    out = subprocess.run(["pdftotext", "-layout", str(pdf), "-"],
                         capture_output=True, text=True)
    if out.returncode != 0:
        raise SystemExit(f"pa: pdftotext failed: {out.stderr[:200]}")
    return out.stdout


def parse_pa(text: str, source_id: str) -> list[dict]:
    records, block = [], []
    for line in text.splitlines():
        m = PA_MAIN_RE.match(line)
        if not m:
            block.append(line)
            continue
        county = m.group(1)
        # -layout keeps 2+ spaces between columns; the city column reads
        # "City, PA zip". When the director column runs into it with a
        # single space the city is ambiguous — omit it (omit-absent).
        city = None
        for tok in re.split(r"\s{2,}", line):
            cm = re.match(r"([A-Za-z .'-]+), PA\b", tok)
            if cm and len(cm.group(1).split()) <= 2:
                city = cm.group(1).strip()
                break
        phone = phone_fmt(line[line.find(", PA"):])
        email = org_email(line) or org_email("\n".join(block))
        desc = (f"County director of veterans affairs office serving "
                f"{county} County, PA. Assists veterans and their families "
                "with VA benefit claims.")
        records.append(record("pa", county, source_id, desc=desc, city=city,
                              phone=phone, email=email))
        block = []
    return records


# --- SC: scdva.sc.gov county-resources grid --------------------------------
# Drupal responsive grid; officer names/personal emails not parsed.

def parse_sc(page: str, source_id: str) -> list[dict]:
    records = []
    for item in re.split(r'views-view-responsive-grid__item-inner', page)[1:]:
        county_m = re.search(r'<h2 class="field-content">([^<]+)</h2>', item)
        if not county_m:
            continue
        county = squash(county_m.group(1))
        tel_m = re.search(r"Telephone:\s*</span><div class=\"field-content\">"
                          r"([^<]+)", item)
        mail_m = re.search(r'href="mailto:([^"]+)"', item)
        records.append(record(
            "sc", county, source_id,
            phone=phone_fmt(tel_m.group(1)) if tel_m else None,
            email=org_email(mail_m.group(1)) if mail_m else None))
    return records


# --- SD: vetaffairs.sd.gov locatevso table ---------------------------------
# Hand-written table, one row per county (ALL-CAPS <strong>), plus a
# trailing tribal-VSO section (skipped — county offices only).

SD_COUNTY_RE = re.compile(
    r"<strong>\s*([A-Z][A-Z &;.'-]{1,}?)[\s;]*(?:&nbsp;|\s|<br\s*/?>)*"
    r"</strong>")


def parse_sd(page: str, source_id: str) -> list[dict]:
    cut = page.find("TRIBAL")
    body = page[:cut] if cut > 0 else page
    marks = [m for m in SD_COUNTY_RE.finditer(body)
             if len(m.group(1).replace("&nbsp;", "").strip()) >= 3]
    by_county: dict[str, dict] = {}
    for i, m in enumerate(marks):
        county = squash(html.unescape(m.group(1))).title()
        if county in by_county:
            continue
        seg = strip_tags(body[m.end(): marks[i + 1].start()
                              if i + 1 < len(marks) else len(body)])
        phone_m = re.search(r"OFFICE:?\s*([\d() .-]{10,})", seg, re.I)
        by_county[county] = record(
            "sd", county, source_id, city=city_of(seg, "sd"),
            phone=phone_fmt(phone_m.group(1)) if phone_m
            else phone_fmt(seg))
    n_tribal = len(SD_COUNTY_RE.findall(page[cut:])) if cut > 0 else 0
    if n_tribal:
        print(f"sd: {n_tribal} tribal VSO entries skipped "
              "(county offices only)")
    return list(by_county.values())


# --- TN: tn.gov county-veterans-services datatable JSON --------------------
# Company "County" rows are the county offices; "TDVS" rows are state
# field offices and are skipped.

def parse_tn(text: str, source_id: str) -> list[dict]:
    records, tdvs = [], 0
    for row in json.loads(text).get("data", []):
        county = (row.get("County") or "").strip()
        if row.get("Company") != "County":
            tdvs += 1
            continue
        if not county:
            continue
        records.append(record(
            "tn", county, source_id,
            city=(row.get("City") or "").strip() or None,
            phone=phone_fmt(row.get("Phone"))))
    if tdvs:
        print(f"tn: {tdvs} TDVS state-office rows skipped")
    return records


# --- WI: wicvso.org accordion (WDVA links here for its CVSO lookup) --------
# su-spoiler per county/tribe; tribal entries skipped; staff names and
# personal emails not parsed. Some upstream links are known-misfiled
# (recorded as published).

def parse_wi(page: str, source_id: str) -> list[dict]:
    records, tribal = [], []
    for sp in re.split(r'<div class="su-spoiler ', page)[1:]:
        title_m = re.search(r'su-spoiler-title[^>]*>.*?<strong>(.*?)</strong>',
                            sp, re.S)
        if not title_m:
            continue
        title = squash(strip_tags(title_m.group(1)))
        if not title.endswith(" County"):
            tribal.append(title)
            continue
        county = title[:-len(" County")]
        body_m = re.search(r'su-spoiler-content[^>]*>(.*)', sp, re.S)
        body = body_m.group(1) if body_m else sp
        text = strip_tags(body)
        no_fax = re.sub(r"(FX|Fax):?\s*[\d() .-]{10,}", "", text, flags=re.I)
        email = None
        for mm in re.finditer(r'href="mailto:([^"]+)"', body):
            email = org_email(mm.group(1))
            if email:
                break
        web_m = re.search(r'<a href="(https?://[^"]+)"[^>]*>[^<]*[Ww]eb\s?site',
                          body)
        records.append(record(
            "wi", county, source_id, city=city_of(text, "wi"),
            phone=phone_fmt(no_fax), email=email,
            website=web_m.group(1) if web_m else None))
    if tribal:
        print(f"wi: {len(tribal)} tribal/non-county entries skipped: "
              f"{', '.join(tribal)}")
    return records


# --- shared PDF helpers (AR / FL / NC) -------------------------------------

def pdf_layout_text(url: str, cache_name: str, force: bool) -> str:
    pdf = fetch(url, SOURCES / "cvso" / cache_name, force=force)
    out = subprocess.run(["pdftotext", "-layout", str(pdf), "-"],
                         capture_output=True, text=True)
    if out.returncode != 0:
        raise SystemExit(f"pdftotext failed on {cache_name}: "
                         f"{out.stderr[:200]}")
    return out.stdout


def column_spans(lines: list[str], min_gap: int = 3) -> list[tuple]:
    """(start, end) spans of a page's text columns, split at vertical
    all-blank gutters at least min_gap chars wide (cf. eoir.find_gutter,
    generalized to any column count)."""
    width = max((len(l) for l in lines), default=0)
    occ = [0] * (width + 1)
    for l in lines:
        for i, ch in enumerate(l):
            if ch != " ":
                occ[i] += 1
    gaps, start = [], None
    for i in range(width + 1):
        if occ[i] == 0:
            if start is None:
                start = i
        else:
            if start is not None and i - start >= min_gap:
                gaps.append((start, i))
            start = None
    if start is not None:
        gaps.append((start, width + 1))
    edges = [0]
    for a, b in gaps:
        if a == 0:
            edges[0] = b
        else:
            edges.append(a)
    spans = list(zip(edges, edges[1:] + [width + 1]))
    return [(a, b) for a, b in spans
            if any(l[a:b].strip() for l in lines)]


COUNTY_INBOX_RE = re.compile(r"cvso|vcso|vso|veteran|vets", re.I)


def county_org_email(text: str) -> str | None:
    """org_email(), plus county-style office inboxes whose local part
    names the office rather than a person (boonecvso@gmail.com,
    veteransdrewcounty@...). First.Last addresses stay excluded."""
    e = org_email(text)
    if e:
        return e
    for m in EMAIL_RE.finditer(text or ""):
        cand = m.group(0)
        if re.match(r"^\w+\.\w+@", cand):
            continue
        if COUNTY_INBOX_RE.search(cand.split("@")[0]):
            return cand.lower()
    return None


def clean_city(fragment: str) -> str | None:
    """City from a captured '<junk>  City' PDF cell: keep the last
    2-plus-space-separated chunk, then drop street residue."""
    city = re.split(r"\s{2,}", fragment.strip())[-1]
    city = re.sub(r"^.*\d\S*\s+", "", city).strip(" ,.")
    return city or None


# --- AR: ADVA VSO/DVSO/CVSO directory PDF ----------------------------------
# One block per county ("X COUNTY" headline, District line, address /
# City, AR zip / Phone / Hours / Email cells). Officer and assistant
# names on the same rows are never parsed (facts-only). The directory
# marks several offices VACANT — those counties still get a record
# (office identity, no phone).

AR_URL = "https://www.veterans.arkansas.gov/s/Directory-5-20-2026.pdf"
AR_HEAD_RE = re.compile(r"^\s*([A-Z][A-Z .&']+?) COUNTY\b")
# upstream quirks: the county is Hot Spring (the PDF says HOT SPRINGS);
# Jefferson's city cell wraps "Pine / Bluff" across lines
AR_COUNTY_FIX = {"Hot Springs": "Hot Spring"}
AR_CITY_FIX = {"Jefferson": "Pine Bluff"}


def parse_ar(text: str, source_id: str) -> list[dict]:
    lines = text.splitlines()
    heads = [(i, m.group(1)) for i, l in enumerate(lines)
             for m in [AR_HEAD_RE.match(l)] if m]
    records = []
    for k, (i, raw) in enumerate(heads):
        end = heads[k + 1][0] if k + 1 < len(heads) else len(lines)
        seg = "\n".join(lines[i:end])
        county = raw.title()
        county = AR_COUNTY_FIX.get(county, county)
        cm = re.search(r"([A-Za-z][A-Za-z .'-]+?),?\s+AR\.?,?\s+\d{5}", seg) \
            or re.search(r"([A-Za-z][A-Za-z .'-]+?),\s+AR\s*$", seg, re.M)
        city = clean_city(cm.group(1)) if cm else None
        city = AR_CITY_FIX.get(county, city)
        pm = re.search(r"(?:Phone|Office):\s*(\(?\d[\d() .\-]{8,})", seg)
        records.append(record(
            "ar", county, source_id, city=city,
            phone=phone_fmt(pm.group(1)) if pm else None,
            email=county_org_email(seg)))
    return records


# --- FL: FDVA CVSO directory PDF (two-column) ------------------------------
# County blocks headed "NAME (n)" (n = 1..67) with "NAME cont." blocks
# for overflow; a block can continue at the top of the same-side column
# of the next page, so per-column cursors carry across pages and the
# heading-less top of each column is attached first (keeping the main
# office's address ahead of satellite offices in the county's text).
# Staff names on the roster lines are never parsed.

FL_URL = ("https://floridavets.org/wp-content/uploads/2026/04/"
          "CVSO-Directory-Apr-2026.pdf")
FL_HEAD_RE = re.compile(r"^([A-Z][A-Z .\-']+?)\s*\((\d+)\)$")
FL_CONT_RE = re.compile(r"^([A-Z][A-Z .\-']+?)\s+[Cc]ont\.?$")
FL_JUNK_RE = re.compile(
    r"County Veterans Service Officers|Updated \w+ \d{4}|^\s*\d+\s*$")
FL_COUNTY_FIX = {"St Johns": "St. Johns", "St Lucie": "St. Lucie",
                 "Desoto": "DeSoto"}


def parse_fl(text: str, source_id: str) -> list[dict]:
    county_txt: dict[str, list] = {}
    numbered: set[int] = set()
    prev_open: list = []
    for page in text.split("\f"):
        lines = [l for l in page.splitlines() if not FL_JUNK_RE.search(l)]
        if not any(l.strip() for l in lines):
            continue
        cols = [[l[a:b].strip() for l in lines]
                for a, b in column_spans(lines)]
        rests = []
        for k, col in enumerate(cols):  # pass 1: page-break overflow
            cur = prev_open[k] if k < len(prev_open) else None
            j = 0
            while j < len(col) and not (FL_HEAD_RE.match(col[j])
                                        or FL_CONT_RE.match(col[j])):
                if cur and col[j] and cur in county_txt:
                    county_txt[cur].append(col[j])
                j += 1
            rests.append((cur, col[j:]))
        prev_open = []
        for cur, rest in rests:  # pass 2: headed blocks
            for l in rest:
                hm = FL_HEAD_RE.match(l) or FL_CONT_RE.match(l)
                if hm:
                    cur = hm.group(1).title()
                    cur = FL_COUNTY_FIX.get(cur, cur)
                    county_txt.setdefault(cur, [])
                    if hm.re is FL_HEAD_RE:
                        numbered.add(int(hm.group(2)))
                elif cur and l:
                    county_txt[cur].append(l)
            prev_open.append(cur)
    missing = set(range(1, 68)) - numbered
    if missing:
        print(f"fl: numbered county headings missing: {sorted(missing)}")
    records = []
    for county, ls in county_txt.items():
        seg = "\n".join(ls)
        cm = re.search(r"([A-Za-z][A-Za-z .'-]+?),?\s+F[Ll]\.?,?\s+\d{5}",
                       seg)
        city = clean_city(cm.group(1)) if cm else None
        pm = re.search(r"(?:Phone|PH|Office|Tel)\b\.?:?\s*"
                       r"(\(?\d[\d() .\-/]{8,})", seg, re.I)
        phone = phone_fmt(pm.group(1)) if pm else None
        if not phone:  # e.g. Sarasota's unlabeled "941-861-8387(VETS)"
            phone = phone_fmt(re.sub(r"Fax:?[^\n]*", "", seg, flags=re.I))
        records.append(record("fl", county, source_id, city=city,
                              phone=phone, email=county_org_email(seg)))
    return records


# --- NC: DMVA Resource Guide 2024-25 county-offices chapter ----------------
# The live milvets.nc.gov no longer publishes a county roster; the
# 2024-25 Resource Guide PDF (fetched from the Internet Archive) holds a
# 4-column COUNTY VETERANS SERVICE OFFICES chapter. Page-wide gutter
# splitting breaks on the pages' decorative sidebars, so cells (2+
# space-separated runs) are assigned to per-page column anchors derived
# from the county-heading x-positions; margin/page-number cells fall
# left of every anchor and are dropped. Counties served by a state
# veterans service center carry that center's contact details with a
# served-through note. Forsyth and Lincoln are absent from the chapter
# upstream (98 of 100 counties).

NC_URL = "https://www.milvets.nc.gov/dmva-resource-guide-202425/open"
NC_ARCHIVE = ("https://web.archive.org/web/20240614012836if_/"
              "https://www.milvets.nc.gov/dmva-resource-guide-202425/open")
NC_HEAD_RE = re.compile(r"^([A-Z][A-Z .\-']+?) COUNTY( ANNEX)?$")
NC_CELL_RE = re.compile(r" {2,}")
NC_COUNTY_FIX = {"Mcdowell": "McDowell", "Swaine": "Swain"}


def parse_nc(text: str, source_id: str) -> list[dict]:
    pages = text.split("\f")
    try:
        start = next(i for i, p in enumerate(pages)
                     if "COUNTY VETERANS SERVICE OFFICES" in p)
    except StopIteration:
        raise SystemExit("nc: county-offices chapter not found — "
                         "guide layout changed")
    county_txt: dict[str, list] = {}
    order: list[str] = []
    prev: dict[int, str] = {}
    for p in pages[start:]:
        if "USDVA" in p or "NCWORKS" in p:
            break  # next chapter
        rows = []
        for l in p.splitlines():
            if "COUNTY VETERANS SERVICE OFFICES" in l:
                continue
            row, pos = [], 0
            for part in NC_CELL_RE.split(l):
                if part.strip():
                    x = l.find(part, pos)
                    row.append((x, part.strip()))
                    pos = x + len(part)
            rows.append(row)
        anchors: list[int] = []
        for a in sorted({x for row in rows for x, t in row
                         if NC_HEAD_RE.match(t)}):
            if not anchors or a - anchors[-1] > 3:
                anchors.append(a)
        if not anchors:
            continue
        cols: dict[int, list] = {i: [] for i in range(len(anchors))}
        for row in rows:
            for x, t in row:
                idx = None
                for i, a in enumerate(anchors):
                    if x >= a - 2:
                        idx = i
                if idx is not None:  # cells left of every anchor: margin
                    cols[idx].append(t)
        cursors = {}
        for i in range(len(anchors)):
            cur, carry = prev.get(i), ""
            for t in cols[i]:
                hm = NC_HEAD_RE.match(t)
                if not hm and t == "COUNTY" and carry \
                        and re.fullmatch(r"[A-Z][A-Z .\-']+", carry) \
                        and not carry.endswith("COUNTY"):
                    hm = NC_HEAD_RE.match(f"{carry} COUNTY")  # wrapped head
                if hm:
                    cur = hm.group(1).title()
                    cur = NC_COUNTY_FIX.get(cur, cur)
                    if cur not in county_txt:
                        county_txt[cur] = []
                        order.append(cur)
                elif cur and t:
                    county_txt[cur].append(t)
                carry = t
            cursors[i] = cur
        prev = cursors

    records = []
    for county in order:
        seg = "\n".join(county_txt[county])
        cm = re.search(r"([A-Za-z][A-Za-z .'-]+?),?\s+NC,?\s+\d{5}", seg)
        desc = ""
        if re.search(r"is served by", seg, re.I):
            desc = (f"County veterans service point for {county} County, "
                    "NC, served through a nearby veterans service center "
                    "(contact details are the serving center's). Assists "
                    "veterans and their families with VA benefit claims.")
        records.append(record(
            "nc", county, source_id, desc=desc,
            city=clean_city(cm.group(1)) if cm else None,
            phone=phone_fmt(seg)))
    return records


# --- registry --------------------------------------------------------------
# st: (publisher, url, title, parse, floor). Default fetch is one GET of
# `url` cached as sources/cvso/<st>.html; FETCHERS override (JSON feeds,
# PDF, per-county crawls, browser-UA-only hosts).

STATES = {
    "al": ("Alabama Department of Veterans Affairs",
           "https://va.alabama.gov/service-officer/",
           "County veterans service offices (service-officer map)",
           parse_al, 55),
    "ar": ("Arkansas Department of Veterans Affairs",
           AR_URL, "VSO, DVSO, CVSO directory (county section)",
           parse_ar, 70),
    "fl": ("Florida Department of Veterans' Affairs",
           FL_URL, "County Veterans Service Officers directory",
           parse_fl, 60),
    "co": ("Colorado Division of Veterans Affairs",
           "https://vets.colorado.gov/county-veterans-service-offices",
           "County veterans service offices", parse_co, 55),
    "ia": ("Iowa Department of Veterans Affairs",
           "https://dva.iowa.gov/county-state-federal-service-map",
           "County veterans service offices (service map listing)",
           parse_ia, 90),
    "il": ("Illinois Department of Veterans' Affairs",
           "https://veterans.illinois.gov/serviceoffices/"
           "vso-locator-countylist.html",
           "Veteran service office county list (content-fragment JSON)",
           parse_il, 70),
    "in": ("Indiana Department of Veterans Affairs",
           "https://www.in.gov/dva/home/cvso-locate/",
           "County veterans service offices (CVSO locate)", parse_in, 85),
    "la": ("Louisiana Department of Veterans Affairs",
           "https://vetaffairs.la.gov/locations",
           "Parish veteran service offices (locations directory)",
           parse_la, 65),
    "mn": ("Minnesota Association of County Veterans Service Officers",
           MN_URL, "Find-a-CVSO county lookup (per-county pages)",
           parse_mn, 80),
    "ms": ("Mississippi Veterans Affairs",
           "https://www.msva.ms.gov/serviceofficers",
           "County veterans service offices", parse_ms, 75),
    "nc": ("North Carolina Department of Military and Veterans Affairs",
           NC_URL,
           "County veterans service offices (DMVA Resource Guide "
           "2024-25)", parse_nc, 90),
    "nd": ("North Dakota Department of Veterans Affairs",
           ND_INDEX,
           "County veterans service officers (find-a-service-officer "
           "county pages)", parse_nd, 45),
    "ne": ("Nebraska Department of Veterans' Affairs",
           "https://veterans.nebraska.gov/cvso",
           "County veterans service offices", parse_ne, 85),
    "nj": ("New Jersey Department of Military and Veterans Affairs",
           "https://www.nj.gov/dva/veterans/services/vso/",
           "Veterans service offices by county", parse_nj, 20),
    "ny": ("New York State Department of Veterans' Services",
           NY_URL,
           "County veterans service agencies (office-locations listing)",
           parse_ny, 50),
    "oh": ("Ohio Department of Veterans Services",
           "https://dvs.ohio.gov/what-we-do/find-a-cvso",
           "County veterans service offices (find-a-CVSO)", parse_oh, 80),
    "or": ("Oregon Department of Veterans' Affairs",
           "https://www.oregon.gov/odva/Services/Pages/"
           "County-Veteran-Services-Offices.aspx",
           "County veteran services offices (locations list API)",
           parse_or, 40),
    "pa": ("Pennsylvania Department of Military and Veterans Affairs",
           PA_URL, "County directors of veterans affairs (MA-VA 400)",
           parse_pa, 60),
    "sc": ("South Carolina Department of Veterans' Affairs",
           "https://scdva.sc.gov/county-resources",
           "County veterans affairs offices", parse_sc, 40),
    "sd": ("South Dakota Department of Veterans Affairs",
           "https://vetaffairs.sd.gov/veteransserviceofficers/locatevso.aspx",
           "County veterans service officers table", parse_sd, 55),
    "tn": ("Tennessee Department of Veterans Services",
           "https://www.tn.gov/veteran/contact-us/"
           "county-veterans-services.html",
           "County veterans service offices (datatable feed)", parse_tn, 85),
    "wi": ("Wisconsin County Veterans Service Officers Association",
           "https://wicvso.org/locate-your-cvso-tvso/",
           "County CVSO directory (linked from WDVA find-my-CVSO)",
           parse_wi, 65),
}

# API-backed states (verified.method = api instead of scrape)
API_STATES = {"il", "or", "tn"}

IL_API = ("https://veterans.illinois.gov/content/soi/veterans/en/"
          "serviceoffices/vso-locator-countylist/jcr:content/responsivegrid/"
          "container/container/contentfragmentlist.model.json")
TN_API = ("https://www.tn.gov/veteran/contact-us/county-veterans-services/"
          "_jcr_content/contentFullWidth/tn_complex_datatable"
          ".exceldriven.json")

FETCHERS = {
    "ar": lambda url, force: pdf_layout_text(url, "ar.pdf", force),
    "co": lambda url, force: fetch(url, SOURCES / "cvso" / "co.html",
                                   force=force, ua=BROWSER_UA
                                   ).read_text(errors="replace"),
    "fl": lambda url, force: pdf_layout_text(url, "fl.pdf", force),
    "nc": lambda url, force: pdf_layout_text(NC_ARCHIVE, "nc.pdf", force),
    "il": lambda url, force: fetch(IL_API, SOURCES / "cvso" / "il.json",
                                   force=force).read_text(errors="replace"),
    "la": fetch_la,
    "mn": fetch_mn,
    "nd": fetch_nd,
    "ny": fetch_ny,
    "oh": lambda url, force: fetch(url, SOURCES / "cvso" / "oh.html",
                                   force=force, ua=BROWSER_UA
                                   ).read_text(errors="replace"),
    "or": fetch_or,
    "pa": fetch_pa,
    "tn": lambda url, force: fetch(TN_API, SOURCES / "cvso" / "tn.json",
                                   force=force).read_text(errors="replace"),
}

# per-state extra source-record fields (NC's live URL 404s since the
# 2026 milvets refresh; the guide is fetched from the Internet Archive)
SOURCE_EXTRAS = {
    "nc": {"archive_url": NC_ARCHIVE,
           "notes": "County roster from the DMVA Resource Guide 2024-25 "
                    "PDF. The live URL 404s since the 2026 milvets.nc.gov "
                    "refresh (which points veterans at county websites "
                    "instead of publishing a roster); fetched from the "
                    "Internet Archive snapshot in archive_url."},
}

# officer-name patterns must never reach a record (facts-only assert)
NAMEY_KEYS = {"_state", "_place_slug", "_name", "categories", "description",
              "address", "phone", "email", "website", "service_area",
              "sources", "verified"}


def main(argv):
    force = "--force" in argv
    states = [a for a in argv if not a.startswith("-")] or sorted(STATES)
    total = 0
    for st in states:
        publisher, url, title, parse, floor = STATES[st]
        if st in FETCHERS:
            page = FETCHERS[st](url, force)
        else:
            page = fetch(url, SOURCES / "cvso" / f"{st}.html",
                         force=force).read_text(errors="replace")
        source_id = write_source(
            "cvso", st, kind="directory", publisher=publisher, title=title,
            url=url, tier="primary", **SOURCE_EXTRAS.get(st, {}))
        records = parse(page, source_id)
        if len(records) < floor:
            raise SystemExit(
                f"{st}: only {len(records)} county offices — floor is {floor}")
        method = "api" if st in API_STATES else "scrape"
        for rec in records:
            extra = set(rec) - NAMEY_KEYS
            assert not extra, f"{st}: unexpected fields {extra}"
            rec["verified"] = Flow(on=today(), method=method)
        replace_records("orgs", source_id, records)
        total += len(records)
    print(f"cvso: {total} county offices across {len(states)} states")


if __name__ == "__main__":
    main(sys.argv[1:])
