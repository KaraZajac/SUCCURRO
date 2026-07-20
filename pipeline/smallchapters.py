"""Five small single-page chapter directories -> org records, one module.

Each publisher gets its own first-class source record and its own
replace_records ownership; a source that breaks (fetch/parse failure or a
count under its sanity floor) is skipped and reported — its existing
records stay on disk untouched — while the others still run.

- Autism Society affiliates (~72): accordion on autismsociety.org/contact-us/
  (#affiliate-list), per-state panels of <p><strong>NAME</strong></p> +
  address/website/phone/email lines. family-support.
- Glisten chapters (15): glisten.org/our-chapters/ accordion, h3 name +
  mailto/external links. lgbtq / lgbtq-youth.
- Bereaved Parents of the USA chapters (~50): find-a-chapter accordion,
  h2 state headings + panel per chapter (tel/mailto inside). Leader person
  names are not copied. family-support / peer-support.
- POMC chapters (32): pomc.org/chapters/, h3 state headings + anchor list.
  family-support / peer-support.
- TransFamilies online groups: The Events Calendar REST feed; recurring
  instances deduped by title (67 events -> ~12 groups). Emitted as national
  online-group orgs; the schedule text lives in the title/description.
  trans-services / family-support.

Facts-only re-expression, attributed (see DATA-RIGHTS.md).

Usage: python3 -m pipeline.smallchapters [--force]
"""
import html
import json
import re
import sys

from .emit import Places, replace_records, today, write_source
from .util import Flow, SOURCES, fetch

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
PHONE_RE = re.compile(r"\(?\b(\d{3})\)?[-. ]\s*(\d{3})[-. ](\d{4})\b")
ZIP_RE = re.compile(r"^\d{5}(-\d{4})?$")

STATE_NAMES = {
    "alabama": "al", "alaska": "ak", "arizona": "az", "arkansas": "ar",
    "california": "ca", "colorado": "co", "connecticut": "ct", "delaware": "de",
    "district of columbia": "dc", "dist. columbia": "dc", "florida": "fl",
    "georgia": "ga", "hawaii": "hi", "idaho": "id", "illinois": "il",
    "indiana": "in", "iowa": "ia", "kansas": "ks", "kentucky": "ky",
    "louisiana": "la", "maine": "me", "maryland": "md", "massachusetts": "ma",
    "michigan": "mi", "minnesota": "mn", "mississippi": "ms", "missouri": "mo",
    "montana": "mt", "nebraska": "ne", "nevada": "nv", "new hampshire": "nh",
    "new jersey": "nj", "new mexico": "nm", "new york": "ny",
    "north carolina": "nc", "north dakota": "nd", "ohio": "oh",
    "oklahoma": "ok", "oregon": "or", "pennsylvania": "pa",
    "puerto rico": "pr", "rhode island": "ri", "south carolina": "sc",
    "south dakota": "sd", "tennessee": "tn", "texas": "tx", "utah": "ut",
    "vermont": "vt", "virginia": "va", "washington": "wa",
    "west virginia": "wv", "wisconsin": "wi", "wyoming": "wy",
}
US_STATE_CODES = set(STATE_NAMES.values())


def strip_tags(fragment: str) -> str:
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", fragment)).split())


def state_from_heading(raw: str) -> str:
    return STATE_NAMES.get(strip_tags(raw).strip().lower(), "")


def find_state(text: str) -> str:
    """Longest US state name mentioned in the text wins."""
    low = " " + " ".join(re.sub(r"[^a-z ]+", " ", text.lower()).split()) + " "
    best, code = "", ""
    for name, c in STATE_NAMES.items():
        if f" {name} " in low and len(name) > len(best):
            best, code = name, c
    return code


def fmt_phone(text: str) -> str | None:
    m = PHONE_RE.search(text)
    return f"{m.group(1)}-{m.group(2)}-{m.group(3)}" if m else None


def ensure_https(url: str) -> str:
    url = html.unescape(url).strip()
    if url.startswith("//"):
        return "https:" + url
    if not re.match(r"https?://", url, re.I):
        return "https://" + url
    return url


def parse_city_state_zip(line: str) -> dict:
    """'Surprise, Arizona 85379' / 'Tucson, AZ 85712' -> {city,state,zip?}."""
    m = re.match(r"^(?P<city>[^,]+?),\s*(?P<st>[A-Za-z. ]+?)\.?\s*"
                 r"(?P<zip>\d{5}(-\d{4})?)?$", line.strip())
    if not m:
        return {}
    st = m["st"].strip().lower()
    st = st if st in US_STATE_CODES and len(st) == 2 else STATE_NAMES.get(st, "")
    if not st:
        return {}
    addr = {"city": m["city"].strip(), "state": st}
    if m["zip"]:
        addr["zip"] = m["zip"]
    return addr


# --- Autism Society -------------------------------------------------------

def autism_society(places, force):
    url = "https://autismsociety.org/contact-us/"
    page = fetch(url, SOURCES / "autismsociety" / "contact-us.html",
                 force=force).read_text(errors="replace")
    sec = page[page.find('id="affiliate-list"'):]
    if len(sec) < 1000:
        raise ValueError("affiliate-list section not found")
    source_id = write_source(
        "autismsociety", "affiliate-list",
        kind="directory", publisher="Autism Society of America",
        title="Autism Society affiliate list (contact-us page)",
        url=url, tier="primary",
    )
    panels = re.findall(
        r'<span class="fusion-toggle-heading">([^<]+)</span>.*?'
        r'<div class="panel-body toggle-content fusion-clearfix">(.*?)</div></div></div>',
        sec, re.S)
    records = []
    for heading, body in panels:
        st_default = state_from_heading(heading)
        # entries begin at a <p> whose text starts with a <strong> name
        chunks = re.split(r"<p[^>]*>(?=\s*<strong>)", body)
        for chunk in chunks:
            m = re.match(r"\s*<strong>(.*?)</strong>", chunk, re.S)
            if not m:
                continue
            name = strip_tags(m.group(1))
            if not name:
                continue
            rec = {
                "_state": st_default, "_place_slug": "", "_name": name,
                "categories": ["family-support"],
                "parent_org": "us/autism-society",
            }
            addr_lines = []
            for pm in re.finditer(r"<p[^>]*>(.*?)</p>", chunk, re.S):
                frag = pm.group(1)
                href = re.search(r'href="([^"]+)"', frag)
                text = strip_tags(frag)
                if not text and not href:
                    continue
                if href and href.group(1).startswith("mailto:"):
                    em = EMAIL_RE.search(href.group(1))
                    if em and "email" not in rec:
                        rec["email"] = em.group(0)
                elif href and "website" not in rec:
                    rec["website"] = ensure_https(href.group(1))
                elif fmt_phone(text) and "phone" not in rec:
                    rec["phone"] = fmt_phone(text)
                elif text and "<strong>" not in frag:
                    addr_lines.append(text)
            csz = {}
            while addr_lines and not csz:
                csz = parse_city_state_zip(addr_lines[-1])
                if csz:
                    addr_lines.pop()
                else:
                    break
            if csz:
                if addr_lines:
                    csz = {"street": ", ".join(addr_lines), **csz}
                rec["_state"] = csz["state"]
                rec["address"] = Flow(csz)
                geoid, _ = places.resolve(csz["state"], csz["city"])
                if geoid:
                    rec["place"] = geoid
            if not rec["_state"]:
                rec["_state"] = find_state(name)
            if not rec["_state"]:
                print(f"smallchapters/autism: no state for {name!r} — skipped")
                continue
            rec["sources"] = [source_id]
            rec["verified"] = Flow(on=today(), method="scrape")
            records.append(rec)
    records.append({
        "_state": "us", "_place_slug": "", "_name": "Autism Society of America",
        "id": "us/autism-society",
        "categories": ["family-support"],
        "description": "National autism organization — local affiliates "
                       "provide information and referral, support, and "
                       "community programming for autistic people and "
                       "their families. National helpline 800-328-8476.",
        "website": "https://autismsociety.org",
        "phone": "800-328-8476",
        "service_area": Flow(kind="national"),
        "sources": [source_id],
        "verified": Flow(on=today(), method="scrape"),
    })
    return source_id, records, 50


# --- Glisten --------------------------------------------------------------

def glisten(places, force):
    url = "https://glisten.org/our-chapters/"
    page = fetch(url, SOURCES / "glisten" / "our-chapters.html",
                 force=force).read_text(errors="replace")
    source_id = write_source(
        "glisten", "chapter-list",
        kind="directory", publisher="Glisten",
        title="Glisten our-chapters page",
        url=url, tier="primary",
    )
    items = re.findall(
        r'<div class="item-content">(.*?)(?=<div class="item-content">|</section>)',
        page, re.S) or re.split(r'(?=<h3 class="xxsmall-title">)', page)[1:]
    records = []
    for item in items:
        nm = re.search(r'<h3 class="xxsmall-title">([^<]+)</h3>', item)
        if not nm:
            continue
        name = strip_tags(nm.group(1))
        if not name.lower().startswith("glisten"):
            continue
        st = find_state(name)
        if not st:
            print(f"smallchapters/glisten: no state for {name!r} — skipped")
            continue
        rec = {
            "_state": st, "_place_slug": "", "_name": name,
            "categories": ["lgbtq", "lgbtq-youth"],
            "parent_org": "us/glisten",
        }
        em = re.search(r'href="mailto:([^"?]+)', item)
        if em:
            rec["email"] = html.unescape(em.group(1)).strip()
        ext = re.search(r'href="(https?://(?!glisten\.org)[^"]+)"[^>]*class="buttons',
                        item)
        if ext:
            rec["website"] = ensure_https(ext.group(1))
        rec["sources"] = [source_id]
        rec["verified"] = Flow(on=today(), method="scrape")
        records.append(rec)
    records.append({
        "_state": "us", "_place_slug": "", "_name": "Glisten",
        "id": "us/glisten",
        "categories": ["lgbtq", "lgbtq-youth"],
        "description": "National organization (formerly GLSEN) working for "
                       "safe and affirming schools for LGBTQ+ youth, with "
                       "state and regional chapters.",
        "website": "https://glisten.org",
        "service_area": Flow(kind="national"),
        "sources": [source_id],
        "verified": Flow(on=today(), method="scrape"),
    })
    return source_id, records, 10


# --- Bereaved Parents of the USA ------------------------------------------

def bpusa(places, force):
    url = "https://bereavedparentsusa.org/find-a-chapter/"
    page = fetch(url, SOURCES / "bpusa" / "find-a-chapter.html",
                 force=force).read_text(errors="replace")
    source_id = write_source(
        "bpusa", "chapter-directory",
        kind="directory", publisher="Bereaved Parents of the USA",
        title="BPUSA find-a-chapter page",
        url=url, tier="primary",
    )
    # position-based walk: h2 state headings and panel titles in document
    # order; a panel's body is the slice up to the next token (the nested
    # accordion divs close inconsistently, so no end-marker regex).
    tokens = []
    for m in re.finditer(r"<h2[^>]*>([^<]+)</h2>", page):
        tokens.append((m.start(), "h2", m.group(1)))
    for m in re.finditer(r'<span class="vc_tta-title-text">([^<]+)</span>', page):
        tokens.append((m.end(), "panel", m.group(1)))
    tokens.sort()
    records, seen, heading = [], set(), ""
    for i, (pos, kind, val) in enumerate(tokens):
        if kind == "h2":
            heading = strip_tags(val).strip().lower()
            continue
        end = tokens[i + 1][0] if i + 1 < len(tokens) else len(page)
        body = page[pos:end]
        name = strip_tags(val)
        if not name:
            continue
        st = state_from_heading(heading)
        if not st:
            # "Virtual Chapters" ("IL - Chicagoland Chapter") and
            # "Siblings Chapters" panels carry their own state hints
            head2 = name.split(" - ", 1)[0].strip().lower()
            if head2 in US_STATE_CODES:
                st = head2
            elif find_state(name):
                st = find_state(name)
            elif "virtual" in heading or name.lower().startswith("national"):
                st = "us"
            else:
                print(f"smallchapters/bpusa: no state for {name!r} "
                      f"(heading {heading!r}) — skipped")
                continue
        # a virtual listing often duplicates the state listing of the same
        # chapter ("IL - Chicagoland Chapter" vs "Chicagoland Chapter")
        key = (st, re.sub(r"^[a-z]{2} - ", "", name.lower()))
        if key in seen:
            continue
        seen.add(key)
        rec = {
            "_state": st, "_place_slug": "", "_name": name,
            "categories": ["family-support", "peer-support"],
            "parent_org": "us/bereaved-parents-usa",
        }
        phone = fmt_phone(strip_tags(body))
        if phone:
            rec["phone"] = phone
        em = re.search(r'href="mailto:([^"?]+)', body)
        if em:
            rec["email"] = html.unescape(em.group(1)).strip()
        w = re.search(r'href="(https?://(?!bereavedparentsusa\.org)[^"]+)"', body)
        if w and "mailto" not in w.group(1):
            rec["website"] = ensure_https(w.group(1))
        rec["sources"] = [source_id]
        rec["verified"] = Flow(on=today(), method="scrape")
        records.append(rec)
    records.append({
        "_state": "us", "_place_slug": "", "_name": "Bereaved Parents of the USA",
        "id": "us/bereaved-parents-usa",
        "categories": ["family-support", "peer-support"],
        "description": "Peer support for parents, grandparents, and "
                       "siblings grieving the death of a child, through "
                       "local chapters.",
        "website": "https://bereavedparentsusa.org",
        "service_area": Flow(kind="national"),
        "sources": [source_id],
        "verified": Flow(on=today(), method="scrape"),
    })
    return source_id, records, 35


# --- Parents of Murdered Children -----------------------------------------

def pomc(places, force):
    url = "https://www.pomc.org/chapters/"
    page = fetch(url, SOURCES / "pomc" / "chapters.html",
                 force=force).read_text(errors="replace")
    source_id = write_source(
        "pomc", "chapter-list",
        kind="directory", publisher="National Organization of Parents of Murdered Children",
        title="POMC chapters page",
        url=url, tier="primary",
    )
    sec = page[page.find("Our Chapters"):]
    if len(sec) < 500:
        raise ValueError("Our Chapters section not found")
    records, seen, st = [], set(), ""
    token_re = re.compile(
        r"<h3[^>]*>([^<]+)</h3>"
        r'|<a href="([^"]+)"[^>]*>([^<]{3,90})</a>')
    for m in token_re.finditer(sec):
        if m.group(1):
            st = state_from_heading(m.group(1))
            continue
        if not st:
            continue
        name = strip_tags(m.group(3))
        href = html.unescape(m.group(2)).strip()
        # require a substantive chapter name — bare "Chapters" anchors are
        # site navigation after the listing ends
        if not name or "chapter" not in name.lower() or len(name) < 10:
            continue
        if name.lower() in seen:  # bi-state chapters are listed twice
            continue
        seen.add(name.lower())
        if href.startswith("/"):
            href = "https://www.pomc.org" + href
        rec = {
            "_state": st, "_place_slug": "", "_name": name,
            "categories": ["family-support", "peer-support"],
            "parent_org": "us/pomc",
            "website": ensure_https(href),
            "sources": [source_id],
            "verified": Flow(on=today(), method="scrape"),
        }
        records.append(rec)
    records.append({
        "_state": "us", "_place_slug": "",
        "_name": "National Organization of Parents of Murdered Children",
        "id": "us/pomc",
        "aliases": ["POMC"],
        "categories": ["family-support", "peer-support"],
        "description": "Support and advocacy for families and friends of "
                       "homicide victims — chapters hold monthly meetings "
                       "and provide court accompaniment. National office "
                       "888-818-7662.",
        "website": "https://www.pomc.org",
        "phone": "888-818-7662",
        "service_area": Flow(kind="national"),
        "sources": [source_id],
        "verified": Flow(on=today(), method="scrape"),
    })
    return source_id, records, 25


# --- TransFamilies --------------------------------------------------------

def transfamilies(places, force):
    api = "https://transfamilies.org/wp-json/tribe/events/v1/events?per_page=50&page={n}"
    events, n = [], 1
    while n <= 5:
        data = json.loads(fetch(api.format(n=n),
                                SOURCES / "transfamilies" / f"events-p{n}.json",
                                force=force).read_text())
        events.extend(data.get("events") or [])
        if n >= int(data.get("total_pages") or 1):
            break
        n += 1
    if not events:
        raise ValueError("no events returned")
    source_id = write_source(
        "transfamilies", "event-feed",
        kind="api-feed", publisher="TransFamilies",
        title="TransFamilies support-group events (The Events Calendar REST API)",
        url="https://transfamilies.org/wp-json/tribe/events/v1/events",
        tier="primary",
    )
    records, seen = [], set()
    for ev in events:
        title = " ".join(html.unescape(ev.get("title") or "").split())
        if not title or title.lower() in seen:
            continue
        seen.add(title.lower())
        m = re.match(r"^(?P<name>.+?)\s*\((?P<sched>[^)]+)\)\s*$", title)
        name = m["name"] if m else title
        sched = m["sched"] if m else ""
        desc = "Online support group for families of transgender and " \
               "gender-diverse children."
        if sched:
            desc += f" Meets {sched}."
        page_url = re.sub(r"/\d{4}-\d{2}-\d{2}/?$", "/", ev.get("url") or "")
        rec = {
            "_state": "us", "_place_slug": "", "_name": name,
            "categories": ["trans-services", "family-support"],
            "parent_org": "us/transfamilies",
            "description": desc,
            "service_area": Flow(kind="national"),
        }
        if page_url:
            rec["website"] = page_url
        rec["sources"] = [source_id]
        rec["verified"] = Flow(on=today(), method="api")
        records.append(rec)
    records.append({
        "_state": "us", "_place_slug": "", "_name": "TransFamilies",
        "id": "us/transfamilies",
        "categories": ["trans-services", "family-support"],
        "description": "Support for families with transgender and "
                       "gender-diverse children — free online peer support "
                       "groups for parents, dads, grandparents, and more.",
        "website": "https://transfamilies.org",
        "service_area": Flow(kind="national"),
        "sources": [source_id],
        "verified": Flow(on=today(), method="api"),
    })
    return source_id, records, 8


SOURCES_FNS = [
    ("autism-society", autism_society),
    ("glisten", glisten),
    ("bpusa", bpusa),
    ("pomc", pomc),
    ("transfamilies", transfamilies),
]


def main(argv):
    force = "--force" in argv
    places = Places()
    total, ok = 0, []
    for label, fn in SOURCES_FNS:
        try:
            source_id, records, floor = fn(places, force)
        except (SystemExit, Exception) as e:  # noqa: BLE001 — skip-and-report
            print(f"smallchapters: {label} BROKEN — skipped ({e})")
            continue
        n_chapters = len(records) - 1  # minus the umbrella record
        if n_chapters < floor:
            print(f"smallchapters: {label} only {n_chapters} chapters "
                  f"(floor {floor}) — skipped, existing records kept")
            continue
        ok.append((label, source_id, records))
        total += len(records)
        print(f"{label}: {n_chapters} chapters + umbrella")
    if total < 180:
        raise SystemExit(f"smallchapters: only {total} records across "
                         f"{len(ok)}/{len(SOURCES_FNS)} sources — floor 180")
    for label, source_id, records in ok:
        replace_records("orgs", source_id, records)


if __name__ == "__main__":
    main(sys.argv[1:])
