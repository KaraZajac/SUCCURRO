"""DBSA chapter directory -> org records (mental-health / peer-support).

The find-a-support-group page is server-rendered WordPress: ?state=XX returns
the full chapter list for that state as `groupInfo` blocks (name, free-form
location line, chapter Email, optional "Visit Website" button, prose body).
All 50 states + DC are fetched throttled and cached under sources/dbsa/.

Two kinds of blocks share the markup: actual chapters ("DBSA <place> Chapter")
and specialty support *groups* nested under a chapter (their location line
names the parent chapter, e.g. "Women's Support Group" @ "DBSA Boston
Chapter"). Only chapter-level blocks (name contains DBSA or Chapter) become
org records — groups are meeting-tree material, not orgs. Regional chapters
are listed under every state they serve; deduped by name, first state wins.
The location line is only sometimes a city ("Torrance", "Chatsworth - DBSA
California Chapter"); a city is extracted only when it resolves against the
place registry. Prose bodies are not copied (facts-only re-expression).

Usage: python3 -m pipeline.dbsa [--force]
"""
import html
import re
import sys

from .emit import Places, norm, replace_records, today, write_source
from .util import Flow, SOURCES, fetch

URL = ("https://www.dbsalliance.org/support/chapters-and-support-groups/"
       "find-a-support-group/?state={st}")

STATES = [
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "DC", "FL", "GA", "HI",
    "ID", "IL", "IN", "IA", "KS", "KY", "LA", "ME", "MD", "MA", "MI", "MN",
    "MS", "MO", "MT", "NE", "NV", "NH", "NJ", "NM", "NY", "NC", "ND", "OH",
    "OK", "OR", "PA", "RI", "SC", "SD", "TN", "TX", "UT", "VT", "VA", "WA",
    "WV", "WI", "WY",
]

NAME_RE = re.compile(r'groupInfo__name">(.*?)</h3>', re.S)
LOC_RE = re.compile(r'groupInfo__location">(.*?)</div>', re.S)
EMAIL_RE = re.compile(r'<strong>Email:\s*</strong><a href="mailto:([^"?]+)"')
WEBSITE_RE = re.compile(r'<a href="([^"]+)"[^>]*>\s*Visit Website\s*</a>')
CHAPTER_RE = re.compile(r"\bDBSA\b|\bChapter\b", re.I)


def strip_tags(fragment: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", "", fragment)).replace("\xa0", " ").strip()


def resolve_city(places: Places, state: str, location: str) -> tuple[str, str] | None:
    """(geoid, city) when the free-form location line names a registry place."""
    location = strip_tags(location)
    candidates = [location]
    # "Chatsworth - DBSA California Chapter", "Chicago and the Midwest Region"
    for sep in (" - ", " – ", ",", " and ", " & "):
        if sep in location:
            candidates.append(location.split(sep)[0])
    for cand in candidates:
        cand = cand.strip()
        if not cand or CHAPTER_RE.search(cand):
            continue
        geoid, _ = places.resolve(state, cand)
        if geoid:
            return geoid, cand
    return None


def main(argv):
    force = "--force" in argv
    places = Places()
    source_id = write_source(
        "dbsa", "chapter-directory",
        kind="directory", publisher="Depression and Bipolar Support Alliance",
        title="DBSA find-a-support-group chapter directory",
        url="https://www.dbsalliance.org/support/chapters-and-support-groups/",
        tier="primary",
    )

    records, seen, blocks_total = [], set(), 0
    for st in STATES:
        cache = SOURCES / "dbsa" / f"state-{st}.html"
        page = fetch(URL.format(st=st), cache, force=force).read_text(errors="replace")
        blocks = re.split(r'<div class="groupInfo prose', page)[1:]
        blocks_total += len(blocks)
        for block in blocks:
            m = NAME_RE.search(block)
            if not m:
                continue
            name = strip_tags(m.group(1))
            if not name or not CHAPTER_RE.search(name):
                continue  # a specialty support group, not a chapter
            key = norm(name)
            if key in seen:  # regional chapters repeat under each state served
                continue
            seen.add(key)
            state = st.lower()
            rec = {
                "_state": state, "_place_slug": "", "_name": name,
                "categories": ["mental-health", "peer-support"],
                "parent_org": "us/dbsa",
            }
            ml = LOC_RE.search(block)
            if ml:
                hit = resolve_city(places, state, ml.group(1))
                if hit:
                    geoid, city = hit
                    rec["address"] = Flow(city=city, state=state)
                    rec["place"] = geoid
            mw = WEBSITE_RE.search(block)
            if mw:
                url = html.unescape(mw.group(1)).strip()
                if url and not url.startswith(("mailto:", "#")):
                    if not re.match(r"https?://", url, re.I):
                        url = "https://" + url
                    rec["website"] = url
            me = EMAIL_RE.search(block)
            if me:
                rec["email"] = html.unescape(me.group(1)).strip()
            rec["sources"] = [source_id]
            rec["verified"] = Flow(on=today(), method="scrape")
            records.append(rec)

    if len(records) < 80:
        raise SystemExit(f"dbsa: only {len(records)} chapters — expected ~90+")
    print(f"parsed {len(records)} chapters from {blocks_total} listing blocks")

    records.append({
        "_state": "us", "_place_slug": "", "_name":
            "Depression and Bipolar Support Alliance",
        "id": "us/dbsa",
        "categories": ["mental-health", "peer-support"],
        "description": "National peer-directed organization for people living "
                       "with depression or bipolar disorder; local chapters run "
                       "free peer support groups.",
        "website": "https://www.dbsalliance.org",
        "service_area": Flow(kind="national"),
        "sources": [source_id],
        "verified": Flow(on=today(), method="scrape"),
    })

    replace_records("orgs", source_id, records)


if __name__ == "__main__":
    main(sys.argv[1:])
