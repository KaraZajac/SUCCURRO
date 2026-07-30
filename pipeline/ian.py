"""Immigration Advocates Network directory -> org records (immigration legal aid).

IAN's National Immigration Legal Services Directory (Pro Bono Net) is the
authoritative national list of nonprofit immigration legal providers. It is
searched one state at a time and server-rendered; there is no offered API, so
this module is **permission-gated** (pipeline/_gate.py): it refuses to write
until IAN answers our request or the DATA-RIGHTS fallback date is reached,
whichever comes first. `--dry-run` parses and reports without writing and
without consulting the gate, so the parser can be maintained meanwhile.

Endpoint shape. `search?state=XX&map=1` returns *every* office in the state on
one page (the paginated `map=0` view caps at 20/page), each as a Google Maps
marker: a `LatLng(lat,lng)` pair plus the same summary card the list view
shows, JS-string-escaped inside `infoWindow.setContent(...)`. One request per
state therefore yields name, upstream id, address, phone, website, email,
coordinates and the legal-areas/service-types rows for the whole state; page 1
of the paginated view is fetched alongside only to cross-check the count.
Per-office detail pages add counties served, detention facilities served,
populations served, languages spoken and non-legal services.

robots.txt (verified 2026-07-30) disallows only `/search/*` — a different path
from the directory's `/nonprofit/legaldirectory/search` — but asks for
`Crawl-delay: 20`, which this module honors, so a cold crawl of the detail
pages runs many hours. `--max-details N` caps new detail fetches per run; every
page is cached under sources/ian/, so repeated runs resume and warm the cache
incrementally. Records parse fine from the summary cards alone, just without
the detail-only fields.

Facts-only, organizational contact only: detail pages carry a Volunteering
block naming a volunteer coordinator with their direct line and email. That
block is cut off the page before any field is read, and contact details are
taken from the summary card only — never a named individual
(smallchapters/bpusa convention). Descriptions are composed here from the
directory's own controlled-vocabulary checkboxes; an org's promotional blurb is
never copied.

Usage: python3 -m pipeline.ian [--force] [--dry-run] [--max-details N]
"""
import html
import json
import re
import sys
import time
from collections import Counter

from . import _gate
from .emit import Places, replace_records, today, write_source
from .util import DATA, Flow, SOURCES, fetch, load_yaml

BASE = "https://www.immigrationadvocates.org/nonprofit/legaldirectory/"
SEARCH = BASE + "search"
# every filter the site's own form submits, so the query is one it already serves
BLANKS = ("national=0&county=&legalArea=&legalService=&nonLegalService="
          "&interestArea=&population=&legalNetwork=&language=&detentionFacility="
          "&text=&zip=&interpreting=0")

SOURCE_ID = "ian/legal-services-directory"
CRAWL_DELAY = 20.0          # robots.txt Crawl-delay (verified 2026-07-30)
PER_PAGE = 20               # list-view page size
FLOOR = 600                 # orgs kept after dedup

STATE_OPT_RE = re.compile(r'<option value="([A-Z]{2})">[A-Z][a-z]')
COUNTY_SELECT_RE = re.compile(r'<select name="county"[^>]*>(.*?)</select>', re.S)
OPTION_RE = re.compile(r'<option value="\d+">([^<]+)</option>')
TOTAL_RE = re.compile(r"Showing Results\s+[\d,]+\s*-\s*[\d,]+\s+of\s+([\d,]+)")
# one map marker per chunk: `myLatLng = new google.maps.LatLng(...)` (the map's
# own `center: new google.maps.LatLng(0, 0)` uses no such variable, so splitting
# on the assignment keeps the centre from swallowing the first office's card)
MARKER_SPLIT = re.compile(r"myLatLng\s*=\s*new google\.maps\.LatLng\(")
COORD_RE = re.compile(r"^(-?[\d.]+),\s*(-?[\d.]+)\)")
CONTENT_RE = re.compile(
    r'infoWindow\.setContent\((".*?")\);\s*infoWindow\.open', re.S)
# the paginated list view renders the same cards as plain HTML
CARD_SPLIT = re.compile(r'<div class="directory-organization-summary')
ORG_HREF_RE = re.compile(
    r'href="/nonprofit/legaldirectory/organization\.(\d+)-([^"]*)"')
NAME_RE = re.compile(r"<h4>\s*<a[^>]*>(.*?)</a>", re.S)
ROW_RE = re.compile(r'<td class="label">\s*(.*?)\s*</td>\s*<td[^>]*>(.*?)</td>', re.S)
WEBSITE_RE = re.compile(r'<a[^>]*href="([^"]+)"[^>]*class="url external')
MAILTO_RE = re.compile(r'href="mailto:([^"?]+)"')
FIRST_LINK_RE = re.compile(r"<a\b")
# hCard address on the detail page — more reliable than the flat summary string
ADR_RE = re.compile(r'<div class="adr location">(.*?)</div>\s*</li>', re.S)
SPAN_RE = {k: re.compile(rf'class="{k}"[^>]*>([^<]*)<')
           for k in ("street-address", "extended-address", "locality",
                     "region", "postal-code")}
# "609 Ridge Road, Suite 210, Lackawanna, NY 14218"
LOC_RE = re.compile(
    r"^(?:(?P<street>.*),\s*)?(?P<city>[^,]+),\s*(?P<st>[A-Za-z]{2})"
    r"(?:\.?\s+(?P<zip>\d{5}(?:-\d{4})?))?$")
# a handful of entries publish only "NY 11364" — state and zip, no city
STATE_ZIP_RE = re.compile(r"^(?P<st>[A-Za-z]{2})\.?\s+(?P<zip>\d{5}(?:-\d{4})?)$")
VOLUNTEER_RE = re.compile(r"<h4>\s*Volunteering\s*</h4>|organization-detail-vcard")
# term separator is a comma + exactly one space (see terms())
TERM_SPLIT = re.compile(r",[ \t](?![ \t])")
NON_STREET = {"", ".", "..", "-", "--", "n/a", "na", "none", "remote",
              "virtual", "no public office", "mailing address only", "tbd"}

# IAN language labels -> ISO 639-1, or 639-3 where no two-letter code exists.
LANGS = {
    "english": "en", "spanish": "es", "french": "fr", "haitian creole": "ht",
    "creole": "ht", "haitian": "ht", "portuguese": "pt", "italian": "it",
    "german": "de", "dutch": "nl", "greek": "el", "hebrew": "he",
    "yiddish": "yi", "arabic": "ar", "farsi": "fa", "persian": "fa",
    "dari": "prs", "pashto": "ps", "pushto": "ps", "urdu": "ur",
    "hindi": "hi", "punjabi": "pa", "panjabi": "pa", "bengali": "bn",
    "bangla": "bn", "gujarati": "gu", "marathi": "mr", "nepali": "ne",
    "sinhala": "si", "tamil": "ta", "telugu": "te", "malayalam": "ml",
    "kannada": "kn", "chinese": "zh", "mandarin": "zh", "cantonese": "zh",
    "taiwanese": "zh", "fukienese": "zh", "fuzhounese": "zh",
    "toisanese": "zh", "mandarin chinese": "zh", "cantonese chinese": "zh",
    "fuganese": "zh", "japanese": "ja", "korean": "ko", "vietnamese": "vi",
    "khmer": "km", "cambodian": "km", "lao": "lo", "laotian": "lo",
    "thai": "th", "burmese": "my", "karen": "kar", "chin": "cnh",
    "rohingya": "rhg", "karenni": "kyu", "hmong": "hmn", "tagalog": "tl",
    "filipino": "tl", "ilocano": "ilo", "cebuano": "ceb", "indonesian": "id",
    "malay": "ms", "malay indonesian": "ms", "kurdish": "ku",
    "mongolian": "mn", "russian": "ru", "ukrainian": "uk", "polish": "pl",
    "czech": "cs", "slovak": "sk", "slovenian": "sl", "croatian": "hr",
    "serbian": "sr", "bosnian": "bs", "macedonian": "mk", "bulgarian": "bg",
    "romanian": "ro", "hungarian": "hu", "albanian": "sq", "turkish": "tr",
    "armenian": "hy", "georgian": "ka", "azerbaijani": "az", "azeri": "az",
    "kazakh": "kk", "kyrgyz": "ky", "tajik": "tg", "turkmen": "tk",
    "uzbek": "uz", "lithuanian": "lt", "latvian": "lv", "estonian": "et",
    "finnish": "fi", "swedish": "sv", "norwegian": "no", "danish": "da",
    "icelandic": "is", "amharic": "am", "tigrinya": "ti", "tigrigna": "ti",
    "oromo": "om", "nuer": "nus", "dinka": "din", "somali": "so",
    "swahili": "sw", "kiswahili": "sw",
    "kinyarwanda": "rw", "kirundi": "rn", "lingala": "ln", "kikongo": "kg",
    "wolof": "wo", "fula": "ff", "fulani": "ff", "pulaar": "ff",
    "bambara": "bm", "mandingo": "man", "malinke": "man", "mandinka": "man",
    "soninke": "snk", "susu": "sus", "sou sou": "sus", "krio": "kri",
    "sierra leonean krio": "kri", "galician": "gl", "gallego": "gl",
    "samoan": "sm", "twi": "ak",
    "akan": "ak", "akan twi": "ak", "ewe": "ee", "ga": "gaa", "yoruba": "yo",
    "igbo": "ig", "hausa": "ha", "edo": "bin", "shona": "sn", "zulu": "zu",
    "xhosa": "xh", "afrikaans": "af", "chichewa": "ny", "tshiluba": "lua",
    "sango": "sg", "malagasy": "mg", "mam": "mam", "kiche": "quc",
    "quiche": "quc", "kanjobal": "kjb", "qanjobal": "kjb", "qeqchi": "kek",
    "kekchi": "kek", "ixil": "ixl", "chuj": "cac", "akateko": "knj",
    "popti": "jac", "jakalteko": "jac", "tzotzil": "tzo", "tzeltal": "tzh",
    "achi": "acr", "poqomchi": "poh", "quechua": "que", "aymara": "ay",
    "nahuatl": "nah", "mixteco": "mix", "mixtec": "mix", "zapoteco": "zap",
    "zapotec": "zap", "triqui": "trc", "purepecha": "tsz",
    "garifuna": "cab", "american sign language": "ase", "asl": "ase",
    "sign language": "ase",
}
LANG_STRIP = re.compile(r"\(.*?\)|[^a-z ]")
# a few entries write sign language as a sentence ("Signers for the deaf: ASL")
SIGN_RE = re.compile(r"\basl\b|sign language", re.I)

DESCRIPTION = "Nonprofit immigration legal services provider."
# corporate boilerplate ignored in the loose existing-org name match
STOPWORDS = {"inc", "incorporated", "corp", "corporation", "llc", "llp",
             "the", "of", "a", "and"}


def strip_tags(fragment: str) -> str:
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", fragment)).split())


def norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", text.lower())


def norm_loose(text: str) -> str:
    """Normalized name minus corporate boilerplate and any parenthetical —
    IAN suffixes branch offices "(New York City Office)"."""
    text = re.sub(r"\(.*?\)", " ", text)
    words = re.sub(r"[^a-z0-9 ]", " ", text.lower()).split()
    return "".join(w for w in words if w not in STOPWORDS)


def clean_phone(raw: str) -> str | None:
    digits = re.sub(r"\D", "", raw or "")
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    if len(digits) == 10 and digits[0] not in "01":
        return f"{digits[:3]}-{digits[3:6]}-{digits[6:]}"
    return None


def clean_url(raw: str) -> str | None:
    url = html.unescape((raw or "").strip())
    if not url or url.lower().startswith("mailto:"):
        return None
    if not re.match(r"https?://", url, re.I):
        url = "https://" + url.lstrip("/")
    return url if re.match(r"https?://[\w.-]+\.[a-z]{2,}", url, re.I) else None


def rows(fragment: str) -> dict[str, str]:
    """label -> raw HTML value for the directory's <td class="label"> tables."""
    return {strip_tags(label).rstrip(":?").strip().lower(): value
            for label, value in ROW_RE.findall(fragment)}


def terms(value: str) -> list[str]:
    """A directory cell is a comma-joined list of controlled-vocabulary terms.
    Commas *inside* a term ("Lesbian,  gay,  bisexual & transgender") are the
    upstream's own, and it writes them with two spaces after — so the term
    separator is a comma followed by exactly one space, and whitespace can't be
    collapsed until after the split."""
    text = html.unescape(re.sub(r"<[^>]+>", " ", value or ""))
    parts = (" ".join(p.split()) for p in TERM_SPLIT.split(text))
    return [p for p in (p.strip(" ,;") for p in parts) if p]


def joined(items: list[str], cap: int) -> str:
    if len(items) <= cap:
        return ", ".join(items)
    return ", ".join(items[:cap]) + f", and {len(items) - cap} more"


def languages(value: str, unknown: Counter) -> list[str]:
    codes: list[str] = []
    for label in terms(value):
        key = " ".join(LANG_STRIP.sub(" ", label.lower()).split())
        code = LANGS.get(key) or LANGS.get(key.replace(" ", ""))
        if not code and SIGN_RE.search(label):
            code = "ase"
        if code:
            if code not in codes:
                codes.append(code)
        elif key:
            unknown[label] += 1
    return codes


def parse_address(summary_location: str, detail: str | None) -> dict:
    """hCard block from the detail page when we have it, else the flat
    "street, city, ST zip" string from the summary card."""
    m = ADR_RE.search(detail) if detail else None
    if m:
        got = {}
        for key, pattern in SPAN_RE.items():
            hit = pattern.search(m.group(1))
            got[key] = strip_tags(hit.group(1)) if hit else ""
        city, state = got["locality"], got["region"].lower()
        if city and len(state) == 2:
            addr = {"city": city, "state": state}
            street = ", ".join(s for s in (got["street-address"],
                                           got["extended-address"]) if s)
            if street.lower().strip(" .") not in NON_STREET:
                addr = {"street": street, **addr}
            if re.fullmatch(r"\d{5}(-\d{4})?", got["postal-code"]):
                addr["zip"] = got["postal-code"]
            return addr
    flat = strip_tags(summary_location or "")
    hit = LOC_RE.match(flat)
    if not hit:
        # no city published: keep the state so the record still shards correctly
        bare = STATE_ZIP_RE.match(flat)
        return {"state": bare["st"].lower()} if bare else {}
    city, state = hit["city"].strip(), (hit["st"] or "").lower()
    if not city or len(state) != 2:
        return {}
    addr = {"city": city, "state": state}
    street = (hit["street"] or "").strip(" ,")
    if street.lower().strip(" .") not in NON_STREET:
        addr = {"street": street, **addr}
    if hit["zip"]:
        addr["zip"] = hit["zip"]
    return addr


def county_name(term: str, state: str) -> str:
    """"Kings (Brooklyn)" -> "Kings". NY lists its Manhattan county as the bare
    state code; the county's actual name is New York."""
    name = re.sub(r"\s*\(.*?\)", "", term).strip()
    return "New York" if name.upper() == "NY" and state == "ny" else name


def service_area(counties: list[str], state: str, in_state: set[str]) -> Flow | None:
    """Counties-served list -> service_area. A list covering (nearly) every
    county the state's own filter offers is statewide coverage."""
    plain = [c for c in (county_name(c, state) for c in counties) if c]
    if not plain:
        return None
    if in_state and len(plain) >= max(3, int(0.9 * len(in_state))):
        return Flow(kind="state", state=state)
    if len(plain) == 1:
        return Flow(kind="county", name=plain[0], state=state)
    label = ", ".join(plain)
    if len(label) <= 110:
        return Flow(kind="regional", name=f"{label} counties", state=state)
    return Flow(kind="regional", state=state)


def describe(cells: dict[str, str], counties: list[str], state: str) -> str:
    """Composed, facts-only summary built from the directory's own checkbox
    vocabularies. The org's promotional description is deliberately not copied."""
    parts = [DESCRIPTION]
    areas = terms(cells.get("areas of immigration legal assistance")
                  or cells.get("areas of legal assistance", ""))
    kinds = terms(cells.get("types of immigration legal services provided")
                  or cells.get("types of legal assistance", ""))
    other = terms(cells.get("other areas of legal assistance", ""))
    nonlegal = terms(cells.get("non-legal services", ""))
    pops = terms(cells.get("populations served", ""))
    facilities = terms(cells.get("detention facilities served", ""))
    if areas:
        parts.append(f"Immigration legal help with: {joined(areas, 8)}.")
    if kinds:
        parts.append(f"Assistance provided: {joined(kinds, 5)}.")
    if other:
        parts.append(f"Other legal help: {joined(other, 6)}.")
    if nonlegal:
        parts.append(f"Non-legal services: {joined(nonlegal, 6)}.")
    if pops:
        parts.append(f"Populations served: {joined(pops, 8)}.")
    if counties:
        parts.append(f"Counties served ({state.upper()}): {joined(counties, 10)}.")
    if facilities:
        parts.append(f"Detention facilities served: {joined(facilities, 4)}.")
    return " ".join(parts)


# ---------------------------------------------------------------- fetching

_last = [0.0]


def slow_fetch(url, cache, force=False):
    """fetch(), spaced at the crawl-delay robots.txt asks for. A cache hit costs
    nothing — only real network requests wait."""
    if cache.exists() and not force:
        return cache
    wait = _last[0] + CRAWL_DELAY - time.monotonic()
    if wait > 0:
        time.sleep(wait)
    try:
        return fetch(url, cache, force=force)
    finally:
        _last[0] = time.monotonic()


def state_url(st: str, mapped: bool, page: int = 1) -> str:
    return f"{SEARCH}?{BLANKS}&state={st}&map={1 if mapped else 0}&page={page}"


def summaries(page: str):
    """(geo|None, summary-card-html) for every marker on a map=1 page."""
    for chunk in MARKER_SPLIT.split(page)[1:]:
        content = CONTENT_RE.search(chunk)
        if not content:
            continue
        try:
            card = json.loads(content.group(1))
        except json.JSONDecodeError:
            continue
        coord = COORD_RE.match(chunk)
        geo = None
        if coord:
            try:
                geo = (float(coord.group(1)), float(coord.group(2)))
            except ValueError:
                geo = None
        yield geo, card


def listed_cards(page: str):
    """(None, summary-card-html) for the paginated list view — the fallback for
    an office the map view has no marker for."""
    for chunk in CARD_SPLIT.split(page)[1:]:
        yield None, chunk.split("</table>")[0]


def take(cards: dict, seen: set, entries, st: str, in_state: set[str]):
    """Register every office in `entries`; first sighting of an id wins."""
    for geo, card in entries:
        m = ORG_HREF_RE.search(card)
        if not m:
            continue
        seen.add(m.group(1))
        cards.setdefault(m.group(1), (m.group(2), card, geo, st.lower(), in_state))


# ---------------------------------------------------------------- existing

def existing_orgs() -> dict[tuple[str, str], str]:
    """(state, normalized name) -> owning source id, over every org already on
    disk except our own — a re-run must not dedup against its own last pull."""
    index: dict[tuple[str, str], str] = {}
    for path in (DATA / "orgs").rglob("*.yaml"):
        rec = load_yaml(path)
        sources = rec.get("sources") or []
        if SOURCE_ID in sources:
            continue
        state = rec["id"].split("/")[0]
        owner = sources[0] if sources else "?"
        for key in (norm(rec["name"]), norm_loose(rec["name"])):
            if key:
                index.setdefault((state, key), owner)
    return index


# ---------------------------------------------------------------- build

def build(card, geo, detail, places, state_hint, in_state, unknown_langs):
    """(record, detail-field flags) or (None, ()) if the card is unusable."""
    m = ORG_HREF_RE.search(card)
    n = NAME_RE.search(card)
    if not m or not n:
        return None, ()
    name = strip_tags(n.group(1))
    if not name:
        return None, ()
    cells = {**rows(detail), **rows(card)} if detail else rows(card)
    counties = terms(cells.get("counties served", ""))
    addr = parse_address(cells.get("location", ""), detail)
    state = addr.get("state") or state_hint
    if len(state) != 2:
        return None, ()

    rec = {"_state": state, "_place_slug": "", "_name": name,
           "categories": ["legal-aid", "immigration-legal"],
           "description": describe(cells, counties, state)}
    if addr.get("city"):
        rec["address"] = Flow(addr)
    if geo and 15 <= geo[0] <= 72 and -180 <= geo[1] <= -60:
        rec["geo"] = Flow(lat=round(geo[0], 5), lng=round(geo[1], 5))
    geoid, _ = places.resolve(state, addr.get("city", ""))
    if not geoid and rec.get("geo"):
        # NYC boroughs and other neighborhood-level "cities" don't match the
        # registry by name; the marker coordinate settles them
        near = places.nearest(rec["geo"]["lat"], rec["geo"]["lng"])
        if near and near[0] == state:
            geoid = near[1]
    if geoid:
        rec["place"] = geoid

    contact = cells.get("contact", "")
    site = WEBSITE_RE.search(contact)
    website = clean_url(site.group(1)) if site else None
    if website:
        rec["website"] = website
    phone = clean_phone(strip_tags(FIRST_LINK_RE.split(contact, maxsplit=1)[0]))
    if phone:
        rec["phone"] = phone
    email = MAILTO_RE.search(contact)
    if email:
        rec["email"] = html.unescape(email.group(1)).strip()

    area = service_area(counties, state, in_state)
    if area:
        rec["service_area"] = area
    langs = languages(cells.get("languages spoken", ""), unknown_langs)
    if langs:
        rec["languages"] = langs

    flags = [flag for flag, present in (
        ("counties-served", counties),
        ("populations-served", terms(cells.get("populations served", ""))),
        ("detention-facilities", terms(cells.get("detention facilities served", ""))),
    ) if present]

    rec["external_ids"] = Flow(ian=m.group(1))
    rec["sources"] = [SOURCE_ID]
    rec["verified"] = Flow(on=today(), method="scrape")
    return rec, flags


def main(argv):
    force = "--force" in argv
    dry = "--dry-run" in argv
    max_details = None
    if "--max-details" in argv:
        max_details = int(argv[argv.index("--max-details") + 1])
    if not dry:
        basis = _gate.require("ian")

    index = slow_fetch(BASE, SOURCES / "ian" / "index.html",
                       force=force).read_text(errors="replace")
    states = sorted(set(STATE_OPT_RE.findall(index)))
    if len(states) < 51:
        raise SystemExit(f"ian: only {len(states)} states in the search form "
                         "— expected 51 (50 states + DC)")

    places = Places()
    known = existing_orgs()
    print(f"ian: {len(known)} existing org name keys loaded for dedup")

    # pass 1 — one map page per state gives every office plus coordinates;
    # page 1 of the list view supplies the count it must agree with
    cards: dict[str, tuple] = {}
    recovered = Counter()
    for st in states:
        listed = slow_fetch(state_url(st, False), SOURCES / "ian" / f"list-{st}.html",
                            force=force).read_text(errors="replace")
        hit = TOTAL_RE.search(listed)
        total = int(hit.group(1).replace(",", "")) if hit else 0
        page = slow_fetch(state_url(st, True), SOURCES / "ian" / f"map-{st}.html",
                          force=force).read_text(errors="replace")
        in_state: set[str] = set()
        cm = COUNTY_SELECT_RE.search(page)
        if cm:
            in_state = {c.strip() for c in OPTION_RE.findall(cm.group(1))}

        seen: set[str] = set()
        take(cards, seen, summaries(page), st, in_state)
        found = len(seen)
        # an office the geocoder failed on has no marker — walk the list view
        if found < total:
            take(cards, seen, listed_cards(listed), st, in_state)
            for n in range(2, (total + PER_PAGE - 1) // PER_PAGE + 1):
                extra = slow_fetch(state_url(st, False, n),
                                   SOURCES / "ian" / f"list-{st}-{n}.html",
                                   force=force).read_text(errors="replace")
                take(cards, seen, listed_cards(extra), st, in_state)
            recovered[st] = len(seen) - found
        print(f"ian {st}: {len(seen)} offices"
              + (f" ({total} listed, {recovered[st]} recovered from the list view)"
                 if recovered[st] else "")
              + ("" if len(seen) == total else f" — listing claims {total}"))

    print(f"ian: {len(cards)} unique offices across {len(states)} states")
    if recovered:
        print(f"ian: offices with no map marker, taken from the list view: "
              f"{dict(recovered)}")

    # pass 2 — detail pages add counties, detention facilities, populations,
    # languages and non-legal services
    details, fetched = {}, 0
    for oid, (slug, *_rest) in sorted(cards.items()):
        cache = SOURCES / "ian" / "orgs" / f"{oid}.html"
        if not cache.exists():
            if max_details is not None and fetched >= max_details:
                continue
            fetched += 1
        page = slow_fetch(f"{BASE}organization.{oid}-{slug}", cache,
                          force=force).read_text(errors="replace")
        details[oid] = VOLUNTEER_RE.split(page)[0]   # drop the volunteer block
    print(f"ian: {len(details)}/{len(cards)} detail pages available "
          f"({fetched} fetched this run)")

    records, unknown_langs = [], Counter()
    skipped, dup_sources, got = Counter(), Counter(), Counter()
    for oid, (_slug, card, geo, st, in_state) in sorted(cards.items()):
        rec, flags = build(card, geo, details.get(oid), places, st, in_state,
                           unknown_langs)
        if rec is None:
            skipped["unparseable"] += 1
            continue
        owner = (known.get((rec["_state"], norm(rec["_name"])))
                 or known.get((rec["_state"], norm_loose(rec["_name"]))))
        if owner:
            skipped["already-listed"] += 1
            dup_sources[owner] += 1
            continue
        for field in ("address", "place", "geo", "phone", "email", "website",
                      "service_area", "languages"):
            if rec.get(field):
                got[field] += 1
        for flag in flags:
            got[flag] += 1
        if oid in details:
            got["detail-page"] += 1
        records.append(rec)

    print(f"ian: {len(records)} orgs kept, {skipped['already-listed']} already "
          f"listed by another source, {skipped['unparseable']} unparseable")
    if dup_sources:
        print("ian: duplicates already owned by "
              + ", ".join(f"{s} ({n})" for s, n in dup_sources.most_common(12)))
    def coverage(fields, denominator, label):
        for field in fields:
            pct = 100 * got[field] / denominator if denominator else 0
            print(f"ian: {got[field]}/{denominator} ({pct:.0f}%) with {field} {label}")

    coverage(("address", "place", "geo", "phone", "email", "website"),
             len(records), "(of all orgs kept)")
    print(f"ian: {got['detail-page']}/{len(records)} "
          f"({100 * got['detail-page'] / len(records) if records else 0:.0f}%) "
          "with a detail page cached")
    # detail-only fields exist only where the detail page has been crawled, so
    # a partial crawl must not be read as thin upstream data
    coverage(("service_area", "languages", "counties-served",
              "populations-served", "detention-facilities"),
             got["detail-page"], "(of orgs with a detail page)")
    if unknown_langs:
        print(f"ian: {len(unknown_langs)} unmapped language labels: "
              + ", ".join(f"{k} x{n}" for k, n in unknown_langs.most_common(15)))

    if dry:
        if len(records) < FLOOR:
            print(f"ian: NOTE — {len(records)} orgs is under the {FLOOR} floor")
        print("dry run — nothing written")
        return
    if len(records) < FLOOR:
        raise SystemExit(f"ian: only {len(records)} orgs kept — floor is {FLOOR}")

    source_id = write_source(
        "ian", "legal-services-directory",
        kind="directory", publisher="Immigration Advocates Network (Pro Bono Net)",
        title="National Immigration Legal Services Directory",
        url=BASE, tier="primary",
        notes=f"Facts-only re-expression of the published directory. {basis}. "
              "Organizational contact only — never named attorneys or staff. "
              "Crawled at the 20-second crawl-delay robots.txt asks for. "
              "Removal or correction on request, honored without argument.",
    )
    assert source_id == SOURCE_ID, source_id
    replace_records("orgs", source_id, records)


if __name__ == "__main__":
    main(sys.argv[1:])
