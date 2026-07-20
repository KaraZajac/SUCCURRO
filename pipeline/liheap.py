"""ACF LIHEAP Clearinghouse office search tool -> site records (utility-assistance).

The public search tool (https://liheapch.acf.gov/search-tool) fronts a small PHP
lookup. A no-county query returns nothing, so statewide coverage means enumerating
every county: states.php (bare) yields the numeric state ids, getCounties.php
yields each state's numeric county ids, and one states.php?State&County&srch=1
page per county yields that county's intake office(s). ~3.2k requests at the
mandatory 1 req/s throttle — roughly an hour cold; every page is cached under
sources/liheap/ so re-runs are instant. Offices repeat across the counties they
serve; dedupe on (name, city) and fold the county list into the description.

Quirk: the host serves its TLS leaf without the Entrust intermediate, so stock
verification fails. We chase the leaf's AIA URL once (plain HTTP, cached) and
install a urllib opener whose SSL context also trusts that intermediate — chain
verification then passes normally and util.fetch needs no changes.

Federal public domain.

Usage: python3 -m pipeline.liheap [--force]
"""
import html
import re
import ssl
import sys
from urllib.request import HTTPSHandler, build_opener, install_opener

from .emit import Places, replace_records, today, write_source
from .util import Flow, SOURCES, fetch

BASE = "https://liheapch.acf.gov/db/"
CACHE = SOURCES / "liheap"

# intermediate CA cert the server fails to send, from the leaf's AIA extension
AIA_CERT_URL = "http://crt.sectigo.com/EntrustDVTLSIssuingRSACA2.crt"

STATE_ABBR = {
    "alabama": "al", "alaska": "ak", "american samoa": "as", "arizona": "az",
    "arkansas": "ar", "california": "ca", "colorado": "co", "connecticut": "ct",
    "delaware": "de", "district of columbia": "dc", "florida": "fl",
    "georgia": "ga", "guam": "gu", "hawaii": "hi", "idaho": "id",
    "illinois": "il", "indiana": "in", "iowa": "ia", "kansas": "ks",
    "kentucky": "ky", "louisiana": "la", "maine": "me", "maryland": "md",
    "massachusetts": "ma", "michigan": "mi", "minnesota": "mn",
    "mississippi": "ms", "missouri": "mo", "montana": "mt", "nebraska": "ne",
    "nevada": "nv", "new hampshire": "nh", "new jersey": "nj",
    "new mexico": "nm", "new york": "ny", "north carolina": "nc",
    "north dakota": "nd", "northern mariana islands": "mp", "ohio": "oh",
    "oklahoma": "ok", "oregon": "or", "pennsylvania": "pa", "puerto rico": "pr",
    "rhode island": "ri", "south carolina": "sc", "south dakota": "sd",
    "tennessee": "tn", "texas": "tx", "utah": "ut", "vermont": "vt",
    "virgin islands": "vi", "virginia": "va", "washington": "wa",
    "west virginia": "wv", "wisconsin": "wi", "wyoming": "wy",
}
USPS = set(STATE_ABBR.values())

OPTION_RE = re.compile(r'<option value="(\d+)"[^>]*>([^<]+)</option>')
# an office block: bolded name (maybe linked), then everything up to the next one
BLOCK_RE = re.compile(r"<strong>(.*?)</strong>(.*?)(?=<strong>|</table>)", re.S)
P_RE = re.compile(r"<p[^>]*>(.*?)</p>", re.S)
HREF_RE = re.compile(r"href='([^']+)'")
TAG_RE = re.compile(r"<[^>]+>")
# zip captured loosely — upstream has typos like 6-digit zips; validated after match
CITY_RE = re.compile(r"^(.*?),\s*([A-Za-z]{2})(?:\s+(\d[\d-]*))?$")
ZIP_RE = re.compile(r"\d{5}(-\d{4})?")


def install_https_context():
    """Trust the missing Entrust intermediate alongside the system roots."""
    der = fetch(AIA_CERT_URL, CACHE / "EntrustDVTLSIssuingRSACA2.crt").read_bytes()
    ctx = ssl.create_default_context()
    ctx.load_verify_locations(cadata=ssl.DER_cert_to_PEM_cert(der))
    install_opener(build_opener(HTTPSHandler(context=ctx)))


def text_of(fragment: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(TAG_RE.sub("", fragment))
                  .replace("\xa0", " ")).strip()


def read_page(url: str, cache, force: bool) -> str:
    return fetch(url, cache, force=force).read_bytes().decode("utf-8", "replace")


def norm_phone(raw: str) -> str:
    digits = re.sub(r"\D", "", raw)
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    if len(digits) == 10:
        return f"{digits[:3]}-{digits[3:6]}-{digits[6:]}"
    return raw.strip()


def parse_offices(page: str, url: str):
    """Yield office dicts from one county result page."""
    if "Results for:" not in page:
        if "No results found." in page:
            return  # legitimate empty state (e.g. defunct county ids)
        raise SystemExit(f"liheap: no 'Results for:' marker — page shape changed: {url}")
    tail = page.split("<!-- DEBUG INFO", 1)
    if len(tail) < 2:
        return  # county registered but no local office listed
    for name_frag, body in BLOCK_RE.findall(tail[1].split("<script type", 1)[0]):
        name = text_of(name_frag)
        if not name:
            continue
        office = {"name": name, "street": [], "city": "", "state": "", "zip": ""}
        m = HREF_RE.search(name_frag)
        if m:
            office["website"] = m.group(1).strip()
        for line_frag in P_RE.findall(body):
            line = text_of(line_frag)
            low = line.lower()
            if not line:
                continue
            if low.startswith("phone:"):
                office.setdefault("phone", norm_phone(line[6:]))
            elif low.startswith("toll free:"):
                office.setdefault("tollfree", norm_phone(line[10:]))
            elif low.startswith(("fax:", "tty", "tdd")):
                continue
            elif low.startswith("email:"):
                office.setdefault("email", line[6:].strip())
            elif low.startswith("website:"):
                m = HREF_RE.search(line_frag)
                if m:
                    office.setdefault("website", m.group(1).strip())
            elif not office["city"]:
                m = CITY_RE.match(line)
                if m and m.group(2).lower() in USPS:
                    office["city"] = m.group(1).strip()
                    office["state"] = m.group(2).lower()
                    z = m.group(3) or ""
                    office["zip"] = z if ZIP_RE.fullmatch(z) else ""
                else:
                    office["street"].append(line)
        yield office


def describe(counties: list[str]) -> str:
    served = ", ".join(counties)
    unit = "County" if len(counties) == 1 else "Counties"
    desc = f"LIHEAP intake office serving {served} {unit}"
    if len(desc) > 200:
        desc = f"LIHEAP intake office serving {len(counties)} counties"
    return desc


def main(argv):
    force = "--force" in argv
    install_https_context()
    places = Places()
    source_id = write_source(
        "acf", "liheap-clearinghouse",
        kind="directory", publisher="ACF LIHEAP Clearinghouse",
        title="LIHEAP local agency directory",
        url="https://liheapch.acf.gov/search-tool", tier="primary",
    )

    states_page = read_page(BASE + "states.php", CACHE / "states.html", force)
    states = OPTION_RE.findall(states_page)
    if len(states) < 50:
        raise SystemExit(f"liheap: only {len(states)} states parsed from state dropdown")

    offices: dict[tuple, dict] = {}
    raw_blocks = empty_counties = skipped_addr_state = 0
    for snum, sname in states:
        st = STATE_ABBR.get(sname.strip().lower())
        if st is None:
            raise SystemExit(f"liheap: unknown state name in dropdown: {sname!r}")
        if st not in places.by_state:
            print(f"skipping {sname.strip()}: not in place registry")
            continue
        counties_page = read_page(f"{BASE}getCounties.php?state={snum}&selected=0",
                                  CACHE / "counties" / f"state-{snum}.html", force)
        counties = OPTION_RE.findall(counties_page)
        if not counties:
            raise SystemExit(f"liheap: no counties parsed for {sname.strip()} (state {snum})")
        for cnum, cname in counties:
            page = read_page(f"{BASE}states.php?State={snum}&County={cnum}&srch=1",
                             CACHE / "offices" / f"s{snum}-c{cnum}.html", force)
            found = False
            for office in parse_offices(page, f"State={snum}&County={cnum}"):
                found = True
                raw_blocks += 1
                addr_st = office["state"] or st
                if addr_st not in places.by_state:
                    skipped_addr_state += 1
                    continue
                office["state"] = addr_st
                key = (office["name"].lower(), office["city"].lower(), addr_st)
                kept = offices.setdefault(key, {**office, "counties": []})
                if cname.strip() not in kept["counties"]:
                    kept["counties"].append(cname.strip())
            if not found:
                empty_counties += 1

    records = []
    for office in offices.values():
        st, city = office["state"], office["city"]
        geoid, place_slug = places.resolve(st, city)
        rec = {
            "_state": st, "_place_slug": place_slug, "_name": office["name"],
            "categories": ["utility-assistance"],
            "description": describe(sorted(office["counties"])),
        }
        if city:
            addr = {"city": city, "state": st}
            if office["street"]:
                addr["street"] = office["street"][0]
            if len(office["street"]) > 1:
                addr["street2"] = "; ".join(office["street"][1:])
            if office["zip"]:
                addr["zip"] = office["zip"]
            rec["address"] = Flow({k: addr[k] for k in
                                   ("street", "street2", "city", "state", "zip")
                                   if k in addr})
        if geoid:
            rec["place"] = geoid
        phone = office.get("phone") or office.get("tollfree")
        if phone:
            rec["phone"] = phone
        if office.get("email"):
            rec["email"] = office["email"]
        if office.get("website"):
            rec["website"] = office["website"]
        rec["sources"] = [source_id]
        rec["verified"] = Flow(on=today(), method="scrape")
        records.append(rec)

    print(f"{raw_blocks} office listings across counties -> {len(records)} unique offices; "
          f"{empty_counties} counties with no office; "
          f"{skipped_addr_state} listings skipped (address state outside place registry)")
    if len(records) < 500:
        raise SystemExit(f"liheap: only {len(records)} offices nationally — expected 500+; aborting")

    replace_records("sites", source_id, records)


if __name__ == "__main__":
    main(sys.argv[1:])
