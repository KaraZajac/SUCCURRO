"""State DV-coalition member-program directories -> org records
(domestic-violence).

Registry-structured (COALITIONS): each scrapeable state coalition has its
own parser and its own source record (<coalition-domain-slug>/
program-directory, following the original nyscadv module), so each
coalition owns exactly its records and re-runs replace per coalition.
The 2026-07 sweep of all 56 NNEDV-listed coalitions found these
server-rendered member-program directories; the rest are JS/map-driven,
login-gated SaaS (Coalition Manager), or publish no local-program list.

DV POLICY — hotline-safe fields only: org name, county/city context in
the description, hotline phone, website. Street addresses are never
recorded for domestic-violence programs even when published (several of
these pages publish them; they are deliberately not parsed), enforced by
a field allowlist assert before emit. See DATA-RIGHTS.md.

Usage: python3 -m pipeline.dvcoalitions [state ...] [--force]
"""
import html
import re
import sys

from .emit import replace_records, today, write_source
from .util import Flow, SOURCES, fetch

PHONE_RE = re.compile(r"\(?\b(\d{3})\)?[-. ]\s*(\d{3})[-. ](\d{4})\b")

# the only keys a DV record may carry (address/geo deliberately absent)
ALLOWED_KEYS = {"_state", "_place_slug", "_name", "categories", "description",
                "phone", "website", "service_area", "sources", "verified"}


def strip_tags(fragment: str) -> str:
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", fragment)).split())


def phone_fmt(text: str) -> str | None:
    """First US phone in `text` as AAA-BBB-CCCC (tel: hrefs or display)."""
    digits = re.sub(r"\D", "", text or "")
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    if len(digits) == 10:
        return f"{digits[:3]}-{digits[3:6]}-{digits[6:]}"
    m = PHONE_RE.search(text or "")
    return f"{m.group(1)}-{m.group(2)}-{m.group(3)}" if m else None


def record(state: str, name: str, source_id: str, *, desc: str = "",
           phone: str | None = None, website: str | None = None,
           service_area=None) -> dict:
    rec = {"_state": state, "_place_slug": "", "_name": name,
           "categories": ["domestic-violence"]}
    if desc:
        rec["description"] = " ".join(desc.split())
    if phone:
        rec["phone"] = phone
    if website:
        rec["website"] = html.unescape(website).strip()
    if service_area:
        rec["service_area"] = service_area
    rec["sources"] = [source_id]
    rec["verified"] = Flow(on=today(), method="scrape")
    return rec


def county_desc(counties: list[str], st: str, unit: str = "County") -> tuple:
    """(sentence, service_area|None) for a served-counties list. Names that
    already carry a suffix ("... area", "Statewide") pass through as-is."""
    plain = [c for c in counties if not c.lower().endswith("area")
             and c.lower() != "statewide"]
    if len(counties) == 1 and len(plain) == 1:
        return (f"Serves {plain[0]} {unit}, {st.upper()}.",
                Flow(kind="county", name=plain[0], state=st))
    names = [c if (c.lower().endswith("area") or c.lower() == "statewide")
             else f"{c} {unit}" for c in counties]
    return f"Serves {', '.join(names)}, {st.upper()}.", None


# --- NY: NYSCADV -----------------------------------------------------------
# <h3>COUNTY</h3> then <ul><li> entries; tel: hrefs are corrupted upstream so
# phones are parsed from display text. Multi-county programs are merged.

def parse_nyscadv(page: str, source_id: str) -> list[dict]:
    start = page.find('id="county-listing"')
    if start < 0:
        raise SystemExit("ny: county-listing anchor not found — layout changed")
    sec = page[start:]
    by_name: dict[str, dict] = {}
    heading_re = re.compile(
        r"<h3[^>]*>(.*?)</h3>(?:(?!</?h3|<ul).)*?<ul>(.*?)</ul>", re.S)
    for hm in heading_re.finditer(sec):
        county = strip_tags(hm.group(1)).strip().title()
        if not county:
            continue
        is_county = county.lower() != "new york city area"
        for li in re.findall(r"<li>(.*?)</li>", hm.group(2), re.S):
            text = strip_tags(li)
            am = re.search(r'<a href="(https?://[^"]+)"[^>]*>(.*?)</a>', li, re.S)
            if am:
                name, website = strip_tags(am.group(2)), am.group(1)
            else:
                name, website = PHONE_RE.split(text)[0].strip(" -–"), ""
            name = name.strip(" -–")
            if not name:
                print(f"ny: unnamed entry under {county} — skipped")
                continue
            phones = list(PHONE_RE.finditer(text))
            phone = (f"{phones[0].group(1)}-{phones[0].group(2)}-"
                     f"{phones[0].group(3)}") if phones else None
            if phones:
                tail = text[phones[-1].end():]
            elif text.startswith(name):
                tail = text[len(name):]
            else:
                tail = ""
            desc = re.sub(r"^(?:[^A-Za-z]+|HOPE\b|or\b|text\b)*", "", tail,
                          flags=re.I).strip()
            label = county if is_county else "New York City area"
            key = name.lower()
            if key in by_name:
                by_name[key]["_counties"].append(label)
                continue
            rec = record("ny", name, source_id, phone=phone, website=website)
            rec["_counties"], rec["_svc"] = [label], desc
            by_name[key] = rec

    records = []
    for rec in by_name.values():
        counties, svc = rec.pop("_counties"), rec.pop("_svc")
        area, sa = county_desc(counties, "ny")
        if sa:
            rec["service_area"] = sa
        rec["description"] = f"{area} {svc}".strip()
        rec = {k: rec[k] for k in ("_state", "_place_slug", "_name",
                                   "categories", "description", "phone",
                                   "website", "service_area", "sources",
                                   "verified") if k in rec}
        records.append(rec)
    return records


# --- AR: domesticpeace.com/shelters ---------------------------------------
# Divi text blocks: <h6>NAME</h6><p><strong>City:</strong> X, AR ...
# <strong>Hotline:</strong> tel ... <a>Website</a></p>. Street addresses
# are not published on this page.

def parse_ar(page: str, source_id: str) -> list[dict]:
    records = []
    for m in re.finditer(r"<h6>(.*?)</h6>\s*<p>(.*?)</p>", page, re.S):
        name, body = strip_tags(m.group(1)), m.group(2)
        if not name:
            continue
        dual = bool(re.search(r"\(Dual\)\s*$", name))
        name = re.sub(r"\s*\(Dual\)\s*$", "", name)
        city_m = re.search(r"City:\s*</strong>\s*([^<]+)", body)
        hot_m = re.search(r"Hotline:\s*</strong>\s*<a href=\"tel:([^\"]+)\"", body)
        web_m = re.search(r'<a href="(https?://[^"]+)"[^>]*>\s*Website', body)
        phone = phone_fmt(hot_m.group(1)) if hot_m else phone_fmt(strip_tags(body))
        city = strip_tags(city_m.group(1)).strip(" ,") if city_m else ""
        what = ("Dual domestic violence and sexual assault program"
                if dual else "Domestic violence shelter program")
        records.append(record(
            "ar", name, source_id,
            desc=f"{what} based in {city}." if city else f"{what}.",
            phone=phone, website=web_m.group(1) if web_m else None))
    return records


# --- DE: dcadv.org get-help/local-programs --------------------------------
# Firespring collection lists under <h4> service-type headings; only the
# DV-specific survivor-service sections are taken (the Information/
# Referrals section is a general referral grab-bag — gambling hotline,
# runaway youth line, APS — and is deliberately excluded, as are the
# batterer-intervention, legal, police, and government sections). Same
# org may appear in several sections — merged.

DE_SECTIONS = ("domestic violence hotline", "shelter, counseling",
               "court advocacy")


def parse_de(page: str, source_id: str) -> list[dict]:
    main = page[page.find("id=main-content"):page.find("footer-container")]
    by_name: dict[str, dict] = {}
    parts = re.split(r"<h4>(.*?)</h4>", main)
    for head, body in zip(parts[1::2], parts[2::2]):
        title = strip_tags(head)
        if not any(k in title.lower() for k in DE_SECTIONS):
            continue
        for li in re.findall(r'<li class="collection-item".*?</li>', body, re.S):
            lab = re.search(r'collection-item-label">(?:<a href="([^"]+)"[^>]*>)?'
                            r"(.*?)</div>", li, re.S)
            if not lab:
                continue
            name = strip_tags(lab.group(2))
            desc_m = re.search(r'collection-item-description">(.*?)</div>', li, re.S)
            desc_text = strip_tags(desc_m.group(1)) if desc_m else ""
            phone = phone_fmt(desc_text)
            svc = PHONE_RE.split(desc_text)[-1].strip(" -–—,;")
            svc = re.sub(r"^(hablamos espa.ol|or\b|and\b)\s*", "", svc,
                         flags=re.I).strip()
            key = name.lower()
            if key in by_name:
                if svc and svc not in by_name[key]["description"]:
                    by_name[key]["description"] += f" {svc}"
                continue
            by_name[key] = record("de", name, source_id, desc=svc,
                                  phone=phone, website=lab.group(1))
    return list(by_name.values())


# --- KY: ZeroV shelter programs -------------------------------------------

def parse_ky(page: str, source_id: str) -> list[dict]:
    records = []
    for block in re.findall(r'class="shelter px-2">.*?</div>\s*</div>', page, re.S):
        name_m = re.search(r"<h3[^>]*>(.*?)</h3>", block, re.S)
        tel_m = re.search(r'href="tel:([^"]+)"', block)
        web_m = re.search(r'<a href="(https?://[^"]+)"[^>]*>\s*Website', block)
        if not name_m:
            continue
        records.append(record(
            "ky", strip_tags(name_m.group(1)), source_id,
            desc="ZeroV member domestic violence shelter program.",
            phone=phone_fmt(tel_m.group(1)) if tel_m else None,
            website=web_m.group(1) if web_m else None))
    return records


# --- LA: LCADV member programs table --------------------------------------
# Columns: program | parishes served | crisis line | website. The page
# repeats the table for mobile — parse the first only.

def parse_la(page: str, source_id: str) -> list[dict]:
    table = next((t for t in re.findall(r"<table.*?</table>", page, re.S)
                  if "Parish Served" in t), None)
    if not table:
        raise SystemExit("la: member-programs table not found")
    records = []
    for row in re.findall(r"<tr[^>]*>(.*?)</tr>", table, re.S):
        tds = re.findall(r"<td[^>]*>(.*?)</td>", row, re.S)
        if len(tds) < 4:
            continue
        name, parishes = strip_tags(tds[0]), strip_tags(tds[1])
        counties = [p.strip() for p in re.split(r",|&|\band\b", parishes)
                    if p.strip()]
        area, sa = county_desc(counties, "la", unit="Parish")
        web_m = re.search(r'href="(https?://[^"]+)"', tds[3])
        records.append(record("la", name, source_id, desc=area,
                              phone=phone_fmt(strip_tags(tds[2])),
                              website=web_m.group(1) if web_m else None,
                              service_area=sa))
    return records


# --- MD: MNADV DV service providers ---------------------------------------
# vc_cta3 sections in three styles: county programs (<h2>County</h2>
# <h4>Program</h4> + "Hotline:"), culturally-specific orgs (<h3>Name</h3>
# + "Office:"), and Family Justice Centers / hospital programs
# (<h2>Name</h2><h4>Helpline: ###</h4>). Street addresses not parsed.

MD_PHONE_RE = re.compile(
    r"(?:24[- ]?hour\s+)?(?:Hotline|Helpline)s?:?\s*([\d() .-]{10,})", re.I)
MD_OFFICE_RE = re.compile(r"Office:?\s*([\d() .-]{10,})", re.I)


def parse_md(page: str, source_id: str) -> list[dict]:
    records = []
    for sec in re.split(r'<section class="vc_cta3-container">', page)[1:]:
        h2 = re.search(r"<h2[^>]*>(.*?)</h2>", sec, re.S)
        h3 = re.search(r"<h3[^>]*>(.*?)</h3>", sec, re.S)
        h4 = re.search(r"<h4[^>]*>(.*?)</h4>", sec, re.S)
        hot_m = MD_PHONE_RE.search(sec) or MD_OFFICE_RE.search(sec)
        phone = phone_fmt(hot_m.group(1)) if hot_m else None
        web_m = re.search(r'<a[^>]+href="(https?://[^"]+)"[^>]*>\s*Learn More', sec)
        website = web_m.group(1) if web_m else None
        h2t = strip_tags(h2.group(1)) if h2 else ""
        h4t = strip_tags(h4.group(1)) if h4 else ""
        if h2t.lower().endswith("county") and h4t:
            desc, sa = county_desc([h2t[:-len("county")].strip()], "md")
            records.append(record("md", h4t, source_id, desc=desc, phone=phone,
                                  website=website, service_area=sa))
        elif h2t and re.match(r"(helpline|hotline)", h4t, re.I):
            records.append(record("md", h2t, source_id, phone=phone,
                                  website=website))
        elif h3 and phone:
            records.append(record("md", strip_tags(h3.group(1)), source_id,
                                  phone=phone, website=website))
        # sections with no phone and no program name are intro banners
    return records


# --- NC: NCCADV service-provider table ------------------------------------
# Search & Filter Pro paginates server-side (?sf_paged=N, 20 rows/page);
# fetch_nc concatenates the pages for the parser.

def fetch_nc(url: str, force: bool) -> str:
    parts = []
    for p in range(1, 10):
        u = url if p == 1 else f"{url}?sf_paged={p}"
        cache = SOURCES / "dvcoalitions" / ("nc.html" if p == 1
                                            else f"nc-p{p}.html")
        text = fetch(u, cache, force=force).read_text(errors="replace")
        parts.append(text)
        if len(re.findall(r'td-mobile-title">Name: ', text)) < 20:
            return "".join(parts)
    raise SystemExit("nc: still paginating after 9 pages — check sf_paged")


def parse_nc(page: str, source_id: str) -> list[dict]:
    records = []
    for row in re.findall(r"<tr>(.*?)</tr>", page, re.S):
        if "service-provider-county" not in row:
            continue
        tds = re.findall(r"<td>(.*?)</td>", row, re.S)
        if len(tds) < 5:
            continue
        name = strip_tags(tds[0]).replace("Name:", "").strip()
        counties = [strip_tags(c) for c in re.findall(
            r'<li class="service-provider-county">(.*?)</li>', tds[2], re.S)]
        crisis = re.search(r"Crisis:\s*<a href=\"tel:([^\"]+)\"", tds[3])
        office = re.search(r"Office:\s*<a href=\"tel:([^\"]+)\"", tds[3])
        phone = phone_fmt((crisis or office).group(1)) if crisis or office else None
        web_m = re.search(r'href="(https?://[^"]+)"', tds[4])
        area, sa = county_desc(counties, "nc")
        records.append(record("nc", name, source_id, desc=area, phone=phone,
                              website=web_m.group(1) if web_m else None,
                              service_area=sa))
    return records


# --- NJ: NJCEDV programs list ---------------------------------------------
# <dl> accordion: <h3>Name</h3><p>County</p>, then a Contact paragraph,
# a Phone heading with the hotline, and a Program Services list.

def parse_nj(page: str, source_id: str) -> list[dict]:
    records = []
    pat = re.compile(r'<div class="opened-header"><h3>(.*?)</h3><p>(.*?)</p>'
                     r".*?</dt>\s*<dd>(.*?)</dd>", re.S)
    for m in pat.finditer(page):
        name, county = strip_tags(m.group(1)), strip_tags(m.group(2))
        dd = m.group(3)
        tel_m = re.search(r'href="tel:([^"]+)"', dd)
        web_m = re.search(r'href="(https?://[^"]+)"', dd)
        contact_m = re.search(r"<h4>Contact</h4>\s*<p>(.*?)</p>", dd, re.S)
        contact = strip_tags(contact_m.group(1)) if contact_m else ""
        contact = re.sub(r"Website:?\s*\S+", "", contact).strip()
        # some Contact paragraphs are an office street address, not a service
        # description — DV policy: drop anything address-shaped
        if re.search(r"\b\d{5}(?:-\d{4})?\b|\bOffice:|\bSuite\b", contact):
            contact = ""
        if county.lower() == "statewide":
            desc, sa = "Serves New Jersey statewide.", Flow(kind="state", state="nj")
        else:
            desc, sa = county_desc([county], "nj")
        records.append(record("nj", name, source_id,
                              desc=f"{desc} {contact}".strip(),
                              phone=phone_fmt(tel_m.group(1)) if tel_m else None,
                              website=web_m.group(1) if web_m else None,
                              service_area=sa))
    return records


# --- OH: ODVN find-help ---------------------------------------------------
# One <li class="location"> per (program, county); merged by program.

def parse_oh(page: str, source_id: str) -> list[dict]:
    by_key: dict[tuple, dict] = {}
    for li in re.findall(r'<li class="location.*?</li>', page, re.S):
        name_m = re.search(r"<h3>(.*?)</h3>", li, re.S)
        county_m = re.search(r'<div class="address">\s*<div>(.*?)</div>', li, re.S)
        phone_m = re.search(r'<span class="phone">(.*?)</span>', li, re.S)
        web_m = re.search(r'<a href="(https?://[^"]+)"[^>]*class="website"', li)
        if not name_m or not county_m:
            continue
        name = strip_tags(name_m.group(1))
        county = strip_tags(county_m.group(1))
        phone = phone_fmt(strip_tags(phone_m.group(1))) if phone_m else None
        key = (name.lower(), phone)
        if key in by_key:
            if county not in by_key[key]["_counties"]:
                by_key[key]["_counties"].append(county)
            continue
        rec = record("oh", name, source_id, phone=phone,
                     website=web_m.group(1) if web_m else None)
        rec["_counties"] = [county]
        by_key[key] = rec

    records = []
    for rec in by_key.values():
        area, sa = county_desc(rec.pop("_counties"), "oh")
        rec["description"] = area
        if sa:
            rec["service_area"] = sa
        rec = {k: rec[k] for k in ("_state", "_place_slug", "_name",
                                   "categories", "description", "phone",
                                   "website", "service_area", "sources",
                                   "verified") if k in rec}
        records.append(rec)
    return records


# --- PA: PCADV program table ----------------------------------------------

def parse_pa(page: str, source_id: str) -> list[dict]:
    records = []
    for row in re.findall(r'<tr\s+data-id="\d+".*?</tr>', page, re.S):
        name_m = re.search(r'<a\s+href="([^"]+)"[^>]*>\s*(.*?)\s*</a>', row, re.S)
        if not name_m:
            continue
        website, name = name_m.group(1), strip_tags(name_m.group(2))
        svc_m = re.search(r'<p class="text--disclaimer">\s*(.*?)</p>', row, re.S)
        tel_m = re.search(r'href="tel:([^"]+)"', row)
        tds = re.findall(r"<td[^>]*>(.*?)</td>", row, re.S)
        counties = []
        if len(tds) >= 3:
            counties = [c.strip() for c in strip_tags(
                tds[2].replace("<br/>", ",").replace("<br />", ",")
                .replace("<br>", ",")).split(",") if c.strip()]
        area, sa = county_desc(counties, "pa") if counties else ("", None)
        svc = strip_tags(svc_m.group(1)) if svc_m else ""
        desc = f"{area} {svc}".strip().rstrip(".") + "." if (area or svc) else ""
        records.append(record("pa", name, source_id, desc=desc,
                              phone=phone_fmt(tel_m.group(1)) if tel_m else None,
                              website=website, service_area=sa))
    return records


# --- PR: Coordinadora Paz para las Mujeres directorio de ayuda ------------
# Card grid: <div class="title-holder"><h4>NAME</h4><p><b>TYPE</b> phones
# ...</p> + social icons; the fa-link icon anchor is the website. Phone
# groups are spaced irregularly ("787-792- 6596").

PR_PHONE_RE = re.compile(r"(\d{3})[-. )]\s*(\d{3})[-. ]\s*(\d{4})")


def parse_pr(page: str, source_id: str) -> list[dict]:
    """One card per (org, service type); same org merged across cards."""
    by_name: dict[str, dict] = {}
    for block in re.split(r'<div class="title-holder">', page)[1:]:
        name_m = re.search(r"<h4>(.*?)</h4>", block, re.S)
        if not name_m:
            continue
        name = strip_tags(name_m.group(1))
        kind_m = re.search(r"<b>(.*?)</b>", block, re.S)
        pm = PR_PHONE_RE.search(strip_tags(block))
        web_m = re.search(r'<a href="(https?://[^"]+)"[^>]*>\s*<i class="fa fa-link"',
                          block)
        kind = strip_tags(kind_m.group(1)).strip(" :") if kind_m else ""
        phone = f"{pm.group(1)}-{pm.group(2)}-{pm.group(3)}" if pm else None
        key = name.lower()
        if key in by_name:
            prev = by_name[key]
            if kind and kind not in prev["_kinds"]:
                prev["_kinds"].append(kind)
            if phone and prev.get("phone") and phone != prev["phone"] \
                    and phone not in prev["_extra"]:
                prev["_extra"].append(phone)
            continue
        rec = record("pr", name, source_id, phone=phone,
                     website=web_m.group(1) if web_m else None)
        rec["_kinds"] = [kind] if kind else []
        rec["_extra"] = []
        by_name[key] = rec

    records = []
    for rec in by_name.values():
        kinds, extra = rec.pop("_kinds"), rec.pop("_extra")
        desc = ("Member organization of Coordinadora Paz para las Mujeres "
                "(Puerto Rico).")
        if kinds:
            desc += f" Listed as: {', '.join(kinds)}."
        for p in extra:
            desc += f" Additional number: {p}."
        rec["description"] = desc
        rec = {k: rec[k] for k in ("_state", "_place_slug", "_name",
                                   "categories", "description", "phone",
                                   "website", "service_area", "sources",
                                   "verified") if k in rec}
        records.append(rec)
    return records


# --- TN: tncoalition help-in-your-area table ------------------------------
# TablePress rows: region | name | DV/SA | office | hotline | counties | web.

def parse_tn(page: str, source_id: str) -> list[dict]:
    records = []
    for row in re.findall(r'<tr class="row-\d+">(.*?)</tr>', page, re.S):
        tds = re.findall(r'<td class="column-\d+">(.*?)</td>', row, re.S)
        if len(tds) < 7:
            continue  # header row uses <th>
        region, name, kind = (strip_tags(t) for t in tds[:3])
        if not name:
            continue
        phone = phone_fmt(strip_tags(tds[4])) or phone_fmt(strip_tags(tds[3]))
        served = strip_tags(tds[5])
        web_m = re.search(r'href="(https?://[^"]+)"', tds[6])
        counties = [c.strip() for c in served.split(",") if c.strip()]
        plain = [c for c in counties if "(" not in c]
        sa = (Flow(kind="county", name=plain[0], state="tn")
              if len(counties) == 1 and plain else None)
        kinds = {"DV": "Domestic violence program",
                 "SA": "Sexual assault program",
                 "DV/SA": "Domestic violence and sexual assault program"}
        desc = (f"{kinds.get(kind, 'Domestic violence program')} "
                f"({region} Tennessee). Counties served: {served}."
                if served else kinds.get(kind, ""))
        records.append(record("tn", name, source_id, desc=desc, phone=phone,
                              website=web_m.group(1) if web_m else None,
                              service_area=sa))
    return records


# --- VA: Action Alliance get-help map markers -----------------------------
# Server-rendered marker divs; the labeled "Serves:", "Hotline:", and
# "Website:" lines are parsed, the trailing street address is not.

def parse_va(page: str, source_id: str) -> list[dict]:
    records, seen = [], set()
    pat = re.compile(r'<div class="marker"[^>]*><h4><a href="[^"]*">(.*?)</a>'
                     r'</h4><div class="content-tooltip"><p>(.*?)</p>', re.S)
    for m in pat.finditer(page):
        name, body = strip_tags(m.group(1)), m.group(2)
        if not name or name.lower() in seen:
            continue
        seen.add(name.lower())
        serves_m = re.search(r"Serves:\s*([^<]+)", body)
        hot_m = re.search(r"Hotline[^:]*:\s*([^<]+)", body)
        web_m = re.search(r'Website:\s*<a href="(https?://[^"]+)"', body)
        phone = phone_fmt(hot_m.group(1)) if hot_m else phone_fmt(strip_tags(body))
        serves = serves_m.group(1).strip().rstrip(",. ") if serves_m else ""
        counties = [c.strip() for c in serves.split(",") if c.strip()]
        sa = None
        if len(counties) == 1 and counties[0].lower().endswith(" county"):
            sa = Flow(kind="county", name=counties[0][:-len(" county")].strip(),
                      state="va")
        # entries whose serves-list already carries state tags (border
        # programs) are left as-is; plain county lists get the VA suffix
        suffix = "" if re.search(r"\b[A-Z]{2}\b", serves) else ", VA"
        records.append(record("va", name, source_id,
                              desc=f"Serves {serves}{suffix}." if serves else "",
                              phone=phone,
                              website=web_m.group(1) if web_m else None,
                              service_area=sa))
    return records


# --- VT: Vermont Network get-help accordion -------------------------------
# One accordion pane per county; programs serving several counties merge.

def parse_vt(page: str, source_id: str) -> list[dict]:
    by_name: dict[str, dict] = {}
    panes = re.split(r'<div class="wp-block-kadence-pane', page)[1:]
    for pane in panes:
        title_m = re.search(r'kt-blocks-accordion-title">([^<]+)</span>', pane)
        if not title_m or not title_m.group(1).strip().endswith("County"):
            continue
        county = title_m.group(1).strip()[:-len("County")].strip()
        heads = list(re.finditer(
            r"<h3[^>]*>\s*(?:<a href=\"(https?://[^\"]+)\"[^>]*>)?(.*?)</h3>",
            pane, re.S))
        for i, hm in enumerate(heads):
            name = strip_tags(hm.group(2))
            if not name:
                continue
            seg = pane[hm.end(): heads[i + 1].start() if i + 1 < len(heads)
                       else len(pane)]
            tel_m = re.search(r'href="tel:([^"]+)"', seg)
            key = name.lower()
            if key in by_name:
                if county not in by_name[key]["_counties"]:
                    by_name[key]["_counties"].append(county)
                continue
            rec = record("vt", name, source_id,
                         phone=phone_fmt(tel_m.group(1)) if tel_m else None,
                         website=hm.group(1))
            rec["_counties"] = [county]
            by_name[key] = rec

    records = []
    for rec in by_name.values():
        area, sa = county_desc(rec.pop("_counties"), "vt")
        rec["description"] = area
        if sa:
            rec["service_area"] = sa
        rec = {k: rec[k] for k in ("_state", "_place_slug", "_name",
                                   "categories", "description", "phone",
                                   "website", "service_area", "sources",
                                   "verified") if k in rec}
        records.append(rec)
    return records


# --- WA: WSCADV program directory -----------------------------------------
# <h2 id="county">County</h2> then class="member" blocks; a hotline-labeled
# phone is preferred over office numbers. King County has sub-area
# headings; those labels pass through as "... area" context.

WA_AREAS = {"South King": "South King County area",
            "Seattle Area": "Seattle area",
            "East King": "East King County area"}


def parse_wa(page: str, source_id: str) -> list[dict]:
    start = page.find('id="member-list"')
    if start < 0:
        raise SystemExit("wa: member-list anchor not found — layout changed")
    sec = page[start:]
    heads = list(re.finditer(r'<h2 id="[^"]*">([^<]+)</h2>', sec))
    by_key: dict[tuple, dict] = {}
    for i, hm in enumerate(heads):
        county = hm.group(1).strip()
        seg = sec[hm.end(): heads[i + 1].start() if i + 1 < len(heads)
                  else len(sec)]
        label = WA_AREAS.get(county, county)
        for block in re.split(r'class="member"', seg)[1:]:
            name_m = re.search(r'member__name">\s*(?:<a href="([^"]+)"[^>]*>)?'
                               r"\s*([^<]+)", block)
            if not name_m:
                continue
            name = name_m.group(2).strip()
            phones = re.findall(r"<span>([^<]*?):?\s*<a href=\"tel:([^\"]+)\"",
                                block)
            phone = None
            for lab, tel in phones:
                if re.search(r"hotline|crisis|24", lab, re.I):
                    phone = phone_fmt(tel)
                    break
            if not phone and phones:
                phone = phone_fmt(phones[0][1])
            key = (name.lower(), name_m.group(1))
            if key in by_key:
                if label not in by_key[key]["_counties"]:
                    by_key[key]["_counties"].append(label)
                continue
            rec = record("wa", name, source_id, phone=phone,
                         website=name_m.group(1))
            rec["_counties"] = [label]
            by_key[key] = rec

    records = []
    for rec in by_key.values():
        counties = rec.pop("_counties")
        if counties == ["Statewide"]:
            rec["description"] = "Serves Washington statewide."
            rec["service_area"] = Flow(kind="state", state="wa")
        else:
            area, sa = county_desc(counties, "wa")
            rec["description"] = area
            if sa:
                rec["service_area"] = sa
        rec = {k: rec[k] for k in ("_state", "_place_slug", "_name",
                                   "categories", "description", "phone",
                                   "website", "service_area", "sources",
                                   "verified") if k in rec}
        records.append(rec)
    return records


# --- WV: WVCADV partners (licensed DV programs) ---------------------------
# The program list ships inside the page's JS map config as 'hover' HTML
# blobs (name, address, phones, website); entries repeat per map region —
# deduped by name. Fax numbers skipped; addresses not parsed.

def parse_wv(page: str, source_id: str) -> list[dict]:
    by_name: dict[str, dict] = {}
    for blob in re.findall(r"'hover':\s*'(.*?)',\s*'url'", page, re.S):
        blob = blob.replace("\\'", "'")
        name_m = re.search(r"<h3[^>]*>(.*?)</h3>", blob, re.S)
        if not name_m:
            continue
        name = strip_tags(name_m.group(1))
        key = name.lower()
        if not name or key in by_name:
            continue
        phone = None
        for p in re.findall(r"<p>(.*?)</p>", blob, re.S):
            text = strip_tags(p)
            if text.lower().startswith("fax"):
                continue
            phone = phone_fmt(text)
            if phone:
                break
        web_m = re.search(r'<a href="(https?://[^"]+)"', blob)
        by_name[key] = record(
            "wv", name, source_id,
            desc="WVCADV partner domestic violence program.",
            phone=phone, website=web_m.group(1) if web_m else None)
    return list(by_name.values())


# --- WY: WCADVSA member programs by county --------------------------------
# <h5 id="county-slug">Name</h5> blocks; a leading * marks shelters.
# Crisis line preferred; the published street address is not parsed.

def parse_wy(page: str, source_id: str) -> list[dict]:
    start = page.find('id="programs-listing"')
    if start < 0:
        raise SystemExit("wy: programs-listing anchor not found — layout changed")
    sec = page[start:]
    heads = list(re.finditer(r'<h5 id="([^"]+)">(.*?)</h5>', sec, re.S))
    records = []
    for i, hm in enumerate(heads):
        county = hm.group(1).replace("-", " ").title()
        raw_name = strip_tags(hm.group(2))
        shelter = raw_name.startswith("*")
        name = raw_name.lstrip("* ").strip()
        seg = sec[hm.end(): heads[i + 1].start() if i + 1 < len(heads)
                  else len(sec)]
        crisis = re.search(r"Crisis Line:\s*<a href=\"tel:([^\"]+)\"", seg)
        office = re.search(r"Office:\s*<a href=\"tel:([^\"]+)\"", seg)
        tel = crisis or office or re.search(r'href="tel:([^"]+)"', seg)
        web_m = re.search(r'<a href="(https?://[^"]+)"[^>]*>\s*(?:Website|Facebook)',
                          seg)
        area, sa = county_desc([county], "wy")
        desc = f"{area} Operates a shelter." if shelter else area
        records.append(record("wy", name, source_id, desc=desc,
                              phone=phone_fmt(tel.group(1)) if tel else None,
                              website=web_m.group(1) if web_m else None,
                              service_area=sa))
    return records


# --- registry --------------------------------------------------------------

COALITIONS = {
    "ar": ("domesticpeace", "https://domesticpeace.com/shelters/",
           "Arkansas Coalition Against Domestic Violence",
           "Arkansas domestic violence shelters", parse_ar, 20),
    "de": ("dcadv", "https://dcadv.org/get-help/local-programs.html",
           "Delaware Coalition Against Domestic Violence",
           "Delaware local domestic violence programs", parse_de, 10),
    "ky": ("zerov", "https://www.zerov.org/shelter_programs",
           "ZeroV", "ZeroV member shelter programs", parse_ky, 12),
    "la": ("lcadv", "https://lcadv.org/get-help/member-programs/",
           "Louisiana Coalition Against Domestic Violence",
           "LCADV member programs", parse_la, 12),
    "md": ("mnadv", "https://www.mnadv.org/get-help/domestic-violence-service-providers/",
           "Maryland Network Against Domestic Violence",
           "Maryland DV service providers", parse_md, 18),
    "nc": ("nccadv", "https://nccadv.org/get-help/",
           "North Carolina Coalition Against Domestic Violence",
           "NCCADV service providers", parse_nc, 60),
    "nj": ("njcedv", "https://njcedv.org/programs/",
           "New Jersey Coalition to End Domestic Violence",
           "NJCEDV member programs", parse_nj, 20),
    "ny": ("nyscadv", "https://www.nyscadv.org/find-help/program-directory.html",
           "New York State Coalition Against Domestic Violence",
           "NYSCADV member program directory", parse_nyscadv, 70),
    "oh": ("odvn", "https://www.odvn.org/find-help/",
           "Ohio Domestic Violence Network",
           "ODVN member program directory", parse_oh, 50),
    "pa": ("pcadv", "https://www.pcadv.org/find-help/find-your-local-domestic-violence-program/",
           "Pennsylvania Coalition Against Domestic Violence",
           "PCADV local program directory", parse_pa, 40),
    "pr": ("pazparalasmujeres", "https://pazparalasmujeres.org/directorio-ayuda/",
           "Coordinadora Paz para las Mujeres",
           "Directorio de ayuda (member organizations)", parse_pr, 12),
    "tn": ("tncoalition", "https://tncoalition.org/get-help/help-in-your-area/",
           "Tennessee Coalition to End Domestic and Sexual Violence",
           "Tennessee help-in-your-area program table", parse_tn, 40),
    "va": ("vsdvalliance", "https://vsdvalliance.org/get-help-ayuda/",
           "Virginia Sexual and Domestic Violence Action Alliance",
           "Action Alliance member agency directory", parse_va, 30),
    "vt": ("vtnetwork", "https://vtnetwork.org/get-help/",
           "Vermont Network Against Domestic and Sexual Violence",
           "Vermont Network member organizations by county", parse_vt, 10),
    "wa": ("wscadv", "https://wscadv.org/washington-domestic-violence-programs/",
           "Washington State Coalition Against Domestic Violence",
           "Washington domestic violence programs", parse_wa, 60),
    "wv": ("wvcadv", "https://wvcadv.org/partners/",
           "West Virginia Coalition Against Domestic Violence",
           "WV domestic violence service programs", parse_wv, 10),
    "wy": ("wyomingdvsa", "https://wyomingdvsa.org/who-we-are/services-member-programs/",
           "Wyoming Coalition Against Domestic Violence and Sexual Assault",
           "Wyoming services and member programs", parse_wy, 15),
}


# coalitions whose directory spans several requests
FETCHERS = {"nc": fetch_nc}


def main(argv):
    force = "--force" in argv
    states = [a for a in argv if not a.startswith("-")] or sorted(COALITIONS)
    for st in states:
        pub, url, publisher, title, parse, floor = COALITIONS[st]
        if st in FETCHERS:
            page = FETCHERS[st](url, force)
        else:
            page = fetch(url, SOURCES / "dvcoalitions" / f"{st}.html",
                         force=force).read_text(errors="replace")
        source_id = write_source(pub, "program-directory", kind="directory",
                                 publisher=publisher, title=title, url=url,
                                 tier="primary")
        records = parse(page, source_id)
        if len(records) < floor:
            raise SystemExit(
                f"{st}: only {len(records)} programs — floor is {floor}")
        for rec in records:
            # DV policy: hotline-safe fields only, never an address — no
            # address-typed fields and nothing address-shaped in descriptions
            extra = set(rec) - ALLOWED_KEYS
            assert not extra, f"{st}: disallowed fields {extra} on {rec['_name']}"
            assert "address" not in rec
            assert not re.search(r"\b\d{5}(?:-\d{4})?\b|\bP\.?O\.? ?Box\b",
                                 rec.get("description", "")), \
                f"{st}: address-shaped description on {rec['_name']}"
        replace_records("orgs", source_id, records)


if __name__ == "__main__":
    main(sys.argv[1:])
