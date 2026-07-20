"""LawHelpNY organization directory -> org records (legal-aid).

lawhelpny.org (Pro Bono Net) enumerates ~670 /organization/<slug> pages in
sitemap.xml, each server-rendered with a schema.org JSON-LD LegalService
block: name, description, telephone, contactPoint.email, postal address,
geo. Quirk: the JSON-LD areaServed is uniformly {"State": "New York"} on
every page — the real per-org coverage is the page's "Locations Served"
term list (<span class="county">), parsed separately; a single county maps
to service_area, anything else (statewide, NYC-boroughs, multi-county) is
described. Throttled crawl cached under sources/lawhelpny/pages/.

Orgs matching an existing LSC grantee program (lsc/grantee-programs) by
normalized name — exact or corporate-suffix-stripped — are skipped: LSC's
own feed is already authoritative for those. Descriptions are composed
(facts-only re-expression, attributed); the upstream blurb is only
consulted to flag immigration-focused orgs.

Usage: python3 -m pipeline.lawhelpny [--force]
"""
import json
import re
import sys
from collections import Counter

from .emit import Places, replace_records, today, write_source
from .util import DATA, Flow, SOURCES, fetch, load_yaml

SITEMAP = "https://www.lawhelpny.org/sitemap.xml"
SITE_URL = "https://www.lawhelpny.org"

LOC_RE = re.compile(
    r"<loc>\s*(https://www\.lawhelpny\.org/organization/[^<]+?)\s*</loc>")
LD_RE = re.compile(
    r'<script type="application/ld\+json"[^>]*>(.*?)</script>', re.S)
REGIONS_RE = re.compile(r'organization-regions--terms">(.*?)</div>', re.S)
SPAN_RE = re.compile(r'<span class="[^"]*">([^<]+)</span>')
ZIP_RE = re.compile(r"\d{5}(-\d{4})?")

GRANTEE_SOURCE = "lsc/grantee-programs"
# corporate boilerplate ignored in the loose LSC name-match pass
STOPWORDS = {"inc", "incorporated", "corp", "corporation", "llc", "the", "of"}

# immigration focus: unambiguous in the name, or repeatedly signalled in the
# org's own blurb (a single passing mention is not "focus")
IMMIG_RE = re.compile(
    r"immigra|refugee|asylum|migrant|deportation|naturaliz|new americans",
    re.I)


def norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", text.lower())


def norm_loose(text: str) -> str:
    words = re.sub(r"[^a-z0-9 ]", "", text.lower()).split()
    return "".join(w for w in words if w not in STOPWORDS)


def grantee_names() -> set[str]:
    """Normalized names (exact + suffix-stripped) of pipeline.lsc's NY
    grantee orgs. NY-only on purpose: loose-matching against all states
    would collide NYC's The Legal Aid Society (not an LSC grantee) with
    Louisville's grantee named plain "Legal Aid Society"."""
    names = set()
    for path in sorted((DATA / "orgs" / "ny").glob("*.yaml")):
        rec = load_yaml(path)
        if GRANTEE_SOURCE in (rec.get("sources") or []):
            names.add(norm(rec["name"]))
            names.add(norm_loose(rec["name"]))
    return names


def text(value) -> str:
    """JSON-LD string field; a handful of pages carry list values
    (multi-line streetAddress)."""
    if isinstance(value, list):
        return ", ".join(v.strip() for v in value
                         if isinstance(v, str) and v.strip())
    return (value or "").strip() if isinstance(value, str) else ""


def phone_fmt(text: str) -> str | None:
    digits = re.sub(r"\D", "", text or "")
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    if len(digits) == 10:
        return f"{digits[:3]}-{digits[3:6]}-{digits[6:]}"
    return None


def legal_service(page: str) -> dict | None:
    for m in LD_RE.finditer(page):
        try:
            data = json.loads(m.group(1))
        except json.JSONDecodeError:
            continue
        for node in data.get("@graph", []):
            if node.get("@type") == "LegalService":
                return node
    return None


def served(page: str) -> list[str]:
    """Locations Served terms; borough aliases ("Kings County | Brooklyn")
    keep the county half."""
    m = REGIONS_RE.search(page)
    if not m:
        return []
    return [s.split("|")[0].strip() for s in SPAN_RE.findall(m.group(1))
            if s.strip()]


def area_fields(terms: list[str]) -> tuple[str, Flow | None]:
    """(serves-sentence, service_area|None) from Locations Served terms."""
    if terms == ["State-wide"]:
        return "Serves New York statewide.", Flow(kind="state", state="ny")
    plain = [t[:-len(" County")] for t in terms if t.endswith(" County")]
    if len(terms) == 1 and len(plain) == 1:
        return (f"Serves {plain[0]} County, NY.",
                Flow(kind="county", name=plain[0], state="ny"))
    if terms:
        return f"Serves {', '.join(terms)}, NY.", None
    return "", None


def main(argv):
    force = "--force" in argv
    places = Places()
    lsc_names = grantee_names()
    sitemap = fetch(SITEMAP, SOURCES / "lawhelpny" / "sitemap.xml",
                    force=force).read_text()
    urls = sorted(set(LOC_RE.findall(sitemap)))
    if len(urls) < 500:
        raise SystemExit(f"lawhelpny: only {len(urls)} organization URLs in "
                         "the sitemap — expected ~670")

    source_id = write_source(
        "lawhelpny", "org-directory",
        kind="directory", publisher="LawHelpNY (Pro Bono Net)",
        title="LawHelpNY legal services organization directory "
              "(sitemap crawl of /organization pages)",
        url=SITE_URL, tier="secondary",
    )

    records, skipped_lsc, skipped, got = [], [], Counter(), Counter()
    for url in urls:
        slug = url.rstrip("/").rsplit("/", 1)[-1]
        page = fetch(url, SOURCES / "lawhelpny" / "pages" / f"{slug}.html",
                     force=force).read_text(errors="replace")
        ls = legal_service(page)
        if not ls or not text(ls.get("name")):
            skipped["no-jsonld"] += 1
            print(f"lawhelpny: skip {slug} — no LegalService JSON-LD")
            continue
        name = " ".join(text(ls.get("name")).split())
        if norm(name) in lsc_names or norm_loose(name) in lsc_names:
            skipped_lsc.append(name)
            continue

        blurb = text(ls.get("description"))
        categories = ["legal-aid"]
        if IMMIG_RE.search(name) or len(IMMIG_RE.findall(blurb)) >= 2:
            categories.append("immigration-legal")

        area, sa = area_fields(served(page))
        rec = {"_state": "ny", "_place_slug": "", "_name": name,
               "categories": categories}
        if area:
            rec["description"] = area

        addr, city = {}, ""
        a = ls.get("address") or {}
        street = text(a.get("streetAddress"))
        city = text(a.get("addressLocality"))
        region = text(a.get("addressRegion")).lower()
        if region == "new york":
            region = "ny"
        if city and len(region) == 2:
            if street:
                addr["street"] = street
            addr["city"] = city
            addr["state"] = region
            zip_code = text(a.get("postalCode"))
            if ZIP_RE.fullmatch(zip_code):
                addr["zip"] = zip_code
            rec["address"] = Flow(addr)
            got["address"] += 1
            geoid, _ = places.resolve(region, city)
            if geoid:
                rec["place"] = geoid
                got["place"] += 1
        g = ls.get("geo") or {}
        try:
            lat, lng = float(g["latitude"]), float(g["longitude"])
            if 15 <= lat <= 72 and -180 <= lng <= -60:
                rec["geo"] = Flow(lat=round(lat, 5), lng=round(lng, 5))
                got["geo"] += 1
        except (KeyError, TypeError, ValueError):
            pass
        phone = phone_fmt(text(ls.get("telephone")))
        if phone:
            rec["phone"] = phone
            got["phone"] += 1
        email = text((ls.get("contactPoint") or {}).get("email"))
        if email:
            rec["email"] = email
            got["email"] += 1
        website = text(ls.get("url"))
        if website and "lawhelpny.org" not in website:
            rec["website"] = website
            got["website"] += 1
        if sa:
            rec["service_area"] = sa
        rec["external_ids"] = Flow(lawhelpny=slug)
        rec["sources"] = [source_id]
        rec["verified"] = Flow(on=today(), method="scrape")
        records.append(rec)

    print(f"lawhelpny: {len(skipped_lsc)} LSC-grantee duplicates skipped: "
          f"{', '.join(sorted(skipped_lsc))}")
    if skipped:
        print("skipped:", dict(skipped))
    for field in ("address", "place", "geo", "phone", "email", "website"):
        print(f"enriched {got[field]}/{len(records)} orgs with {field}")
    if len(records) < 400:
        raise SystemExit(f"lawhelpny: only {len(records)} orgs kept — "
                         "floor is 400")
    replace_records("orgs", source_id, records)


if __name__ == "__main__":
    main(sys.argv[1:])
