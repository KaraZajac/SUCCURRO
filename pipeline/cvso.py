"""County Veteran Service Officer directories -> org records (veterans).

No national CVSO roster exists; state veterans agencies publish (or
don't) a county-office directory on their own sites. Registry-structured
(STATES, like dvcoalitions.COALITIONS): each state with a parseable
county directory gets its own parser and its own per-state source record
under the shared "cvso/" prefix (data/sources/cvso/<st>.yaml, id
cvso/<st>), so each state's re-run replaces exactly its own records.
Pages/feeds cache under sources/cvso/.

2026-07 all-state survey summary (see module registry for the built
set): built 16 states; JS/blocked with no recoverable feed: CA, KS, MA,
NH, VA; PDF-only left unbuilt: AR, FL (multi-column), NC (interleaved
3-column), TX (county->website only); buildable but multi-page crawls
deferred: LA, ND, NY; state-office systems only (no county roster): AK,
AZ, CT, DE, GA, HI, ID, KY, MD, ME, MO*, MT, NM, NV, OK, RI, UT, VT,
WA, WV, WY (*MO's ArcGIS feed is state-run offices; MI similar).

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


# --- registry --------------------------------------------------------------
# st: (publisher, url, title, parse, floor). Default fetch is one GET of
# `url` cached as sources/cvso/<st>.html; FETCHERS override (JSON feeds,
# PDF, per-county crawls, browser-UA-only hosts).

STATES = {
    "al": ("Alabama Department of Veterans Affairs",
           "https://va.alabama.gov/service-officer/",
           "County veterans service offices (service-officer map)",
           parse_al, 55),
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
    "mn": ("Minnesota Association of County Veterans Service Officers",
           MN_URL, "Find-a-CVSO county lookup (per-county pages)",
           parse_mn, 80),
    "ms": ("Mississippi Veterans Affairs",
           "https://www.msva.ms.gov/serviceofficers",
           "County veterans service offices", parse_ms, 75),
    "ne": ("Nebraska Department of Veterans' Affairs",
           "https://veterans.nebraska.gov/cvso",
           "County veterans service offices", parse_ne, 85),
    "nj": ("New Jersey Department of Military and Veterans Affairs",
           "https://www.nj.gov/dva/veterans/services/vso/",
           "Veterans service offices by county", parse_nj, 20),
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
    "co": lambda url, force: fetch(url, SOURCES / "cvso" / "co.html",
                                   force=force, ua=BROWSER_UA
                                   ).read_text(errors="replace"),
    "il": lambda url, force: fetch(IL_API, SOURCES / "cvso" / "il.json",
                                   force=force).read_text(errors="replace"),
    "mn": fetch_mn,
    "oh": lambda url, force: fetch(url, SOURCES / "cvso" / "oh.html",
                                   force=force, ua=BROWSER_UA
                                   ).read_text(errors="replace"),
    "or": fetch_or,
    "pa": fetch_pa,
    "tn": lambda url, force: fetch(TN_API, SOURCES / "cvso" / "tn.json",
                                   force=force).read_text(errors="replace"),
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
            url=url, tier="primary")
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
