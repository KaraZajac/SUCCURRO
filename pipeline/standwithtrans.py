"""Stand with Trans support groups -> meeting records (+ org records).

standwithtrans.org (WordPress/Divi, server-rendered) lists its Community
Connections peer groups on one page: inside "Groups Available" accordion
panels, each group is a `<p><strong>TITLE</strong></p>` ("2nd Thursday Teen
Group–Zoom", "1st Tuesday Parent Group–Oakland County, MI") followed by a
description paragraph with a regular schedule phrase ("2nd Thursday of each
month, from 7-8:30 p.m. Eastern") plus audience and facilitator sentences.
Facilitator person names are not copied. The Creative Connections page adds a
weekly teen art group ("every Monday from 5:00–6:00 PM" at Brighton
Lighthouse). Zoom groups are online/national; the MI groups are in person
(the trans men group meets at Affirmations in Ferndale, MI).

Stand with Trans itself already exists as an org record from CenterLink's
member directory (mi/stand-with-trans) — that record is reused as the
meetings' org FK, not duplicated; this module emits an org only for the Ally
Parents program (trained volunteer parents reachable by text via
833-435-7798), and falls back to writing the umbrella org itself only if the
CenterLink record ever disappears.

Facts-only re-expression, attributed (see DATA-RIGHTS.md).

Usage: python3 -m pipeline.standwithtrans [--force]
"""
import html as htmllib
import re
import sys

from .emit import Places, norm, replace_records, today, write_source
from .util import DATA, Flow, SOURCES, fetch, load_yaml

GROUPS_URL = "https://standwithtrans.org/community-connections/"
ART_URL = "https://standwithtrans.org/creative-connections/"

GROUP_RE = re.compile(
    r"<p[^>]*><strong>(.*?)</strong></p>\s*<p[^>]*>(.*?)</p>", re.S)
SCHED_RE = re.compile(
    r"((?:1st|2nd|3rd|4th|5th|last)(?:\s*(?:and|&amp;|&)\s*(?:1st|2nd|3rd|4th|5th))?\s+"
    r"(?P<day>Mon|Tues|Wednes|Thurs|Fri|Satur|Sun)days?\s*of each month)"
    r".{0,20}?from\s+(?P<h1>\d{1,2})(?::(?P<m1>\d{2}))?\s*[–-]\s*"
    r"(?P<h2>\d{1,2})(?::(?P<m2>\d{2}))?\s*(?P<mer>[ap])\.?m\b"
    r"[^A-Za-z]{0,6}(?P<tz>Eastern|Central|Mountain|Pacific)?", re.I | re.S)
DAY_TOKEN = {"mon": "mon", "tues": "tue", "wednes": "wed", "thurs": "thu",
             "fri": "fri", "satur": "sat", "sun": "sun"}
TZ_SHORT = {"eastern": "ET", "central": "CT", "mountain": "MT", "pacific": "PT"}
VENUE_RE = re.compile(r"\bat\s+([A-Z][\w' ]{2,40}?)\s+in\s+([A-Z][\w' ]{2,30}?),\s*MI\b")
# person names ("facilitated by Gabriel D. and Andrew H.") are not copied;
# initials carry periods, so scrub up to the next known sentence opener
FACIL_RE = re.compile(
    r",?\s*and is facilitated by.*?(?=Registration|Meeting location|$)", re.I | re.S)

CATEGORIES = ["trans-services", "family-support", "peer-support"]
ORG_ID = "mi/stand-with-trans"


def strip_tags(fragment: str) -> str:
    text = htmllib.unescape(re.sub(r"<br\s*/?>", " ", fragment))
    text = re.sub(r"<[^>]+>", "", text)
    return re.sub(r"\s+", " ", text).strip()


def parse_schedule(text: str):
    """'2nd Thursday of each month, from 7-8:30 p.m. Eastern' ->
    (scheduleEntry, tz) or (None, None). The meridiem is given once, on the
    end time; a start later than the end inherits it minus 12h."""
    m = SCHED_RE.search(text)
    if not m:
        return None
    end = int(m["h2"]) % 12 * 60 + int(m["m2"] or 0) + \
        (720 if m["mer"].lower() == "p" else 0)
    start = int(m["h1"]) % 12 * 60 + int(m["m1"] or 0) + \
        (720 if m["mer"].lower() == "p" else 0)
    if start > end:
        start -= 720
    note = re.sub(r"\s+", " ", m.group(1))
    if m["tz"]:
        note += f" ({TZ_SHORT[m['tz'].lower()]})"
    entry = Flow(day=DAY_TOKEN[m["day"].lower()], time=f"{start // 60:02d}:{start % 60:02d}")
    if 0 < end - start <= 480:
        entry["duration_min"] = end - start
    entry["note"] = note
    return entry


def group_meetings(places, org_id, source_id, force):
    page = fetch(GROUPS_URL, SOURCES / "standwithtrans" / "community-connections.html",
                 force=force).read_text(errors="replace")
    records = []
    for title_html, desc_html in GROUP_RE.findall(page):
        title = strip_tags(title_html)
        if "group" not in title.lower():
            continue
        desc = strip_tags(desc_html)
        entry = parse_schedule(desc)
        if not entry:
            print(f"standwithtrans: no parseable schedule for {title!r}: {desc[:80]!r}")
            continue
        online = "zoom" in title.lower() or "zoom" in desc.lower()
        rec = {
            "_state": "us" if online else "mi",
            "_place_slug": "online",
            "_name": re.sub(r"\s*[–-]+\s*(Zoom|Oakland County, MI)\s*$", "", title,
                            flags=re.I) or title,
            "program": "stand-with-trans",
            "categories": CATEGORIES,
            "org": org_id,
            "schedule": [entry],
            "format": "online" if online else "in-person",
        }
        vm = VENUE_RE.search(desc)
        if vm and not online:
            rec["venue_name"] = vm.group(1).strip()
            city = vm.group(2).strip()
            rec["venue"] = Flow(city=city, state="mi")
            geoid, slug = places.resolve("mi", city)
            rec["_place_slug"] = slug
            if geoid:
                rec["place"] = geoid
        elif not online:
            # regional group with no published venue ("location provided
            # after registration") — shard under the county seat-less slug
            rec["_place_slug"] = "oakland-county"
        notes = FACIL_RE.sub(". ", desc)
        notes = notes[notes.find("This group"):] if "This group" in notes else ""
        if notes:
            notes = re.sub(r"\.\s*[.,]", ".", re.sub(r"\s+", " ", notes)).strip()
            rec["notes"] = notes[:200]
        rec["url"] = GROUPS_URL
        rec["sources"] = [source_id]
        rec["verified"] = Flow(on=today(), method="scrape")
        records.append(rec)
    return records


def art_meeting(places, org_id, source_id, force):
    page = fetch(ART_URL, SOURCES / "standwithtrans" / "creative-connections.html",
                 force=force).read_text(errors="replace")
    text = strip_tags(re.sub(r"<script.*?</script>|<style.*?</style>", "", page,
                             flags=re.S))
    m = re.search(r"every\s+(Mon|Tues|Wednes|Thurs|Fri|Satur|Sun)day\s+from\s+"
                  r"(\d{1,2})(?::(\d{2}))?\s*[–-]\s*(\d{1,2})(?::(\d{2}))?\s*"
                  r"([AP])\.?M\b", text, re.I)
    if not m:
        print("standwithtrans: Creative Connections schedule not found — skipped")
        return []
    end = int(m[4]) % 12 * 60 + int(m[5] or 0) + (720 if m[6].lower() == "p" else 0)
    start = int(m[2]) % 12 * 60 + int(m[3] or 0) + (720 if m[6].lower() == "p" else 0)
    if start > end:
        start -= 720
    entry = Flow(day=DAY_TOKEN[m[1].lower()], time=f"{start // 60:02d}:{start % 60:02d}",
                 note="weekly")
    if 0 < end - start <= 480:
        entry["duration_min"] = end - start
    rec = {
        "_state": "mi", "_place_slug": "brighton", "_name": "Creative Connections",
        "program": "stand-with-trans",
        "categories": CATEGORIES,
        "org": org_id,
        "schedule": [entry],
        "format": "in-person",
        "notes": "Art group for teens ages 13-18, led by an art therapist. "
                 "No art experience needed.",
        "url": ART_URL,
        "sources": [source_id],
        "verified": Flow(on=today(), method="scrape"),
    }
    vm = re.search(r"gather at ([A-Z][\w' ]{2,40}?)(?:\s+to\b|[.,])", text)
    if vm:
        rec["venue_name"] = vm.group(1).strip()
    return [rec]


def existing_org_id(source_id: str) -> str | None:
    """The Stand with Trans org another source (CenterLink) already owns."""
    for path in sorted((DATA / "orgs").rglob("stand-with-trans*.yaml")):
        rec = load_yaml(path)
        if norm(rec["name"]) == "standwithtrans" and \
                source_id not in (rec.get("sources") or []):
            return rec["id"]
    return None


def main(argv):
    force = "--force" in argv
    places = Places()
    source_id = write_source(
        "standwithtrans", "support-groups",
        kind="org-website", publisher="Stand with Trans",
        title="Stand with Trans Community Connections and Creative Connections pages",
        url=GROUPS_URL, tier="primary",
    )

    org_id = existing_org_id(source_id)
    if org_id:
        print(f"standwithtrans: linking meetings to existing org {org_id} "
              "(CenterLink-owned; not duplicated)")
    orgs = [
        {
            "_state": "mi", "_place_slug": "", "_name": "Ally Parents",
            "categories": ["trans-services", "family-support", "peer-support"],
            "parent_org": org_id or ORG_ID,
            "description": "Trained, vetted volunteer parents of trans "
                           "individuals offering affirming peer support to "
                           "trans/nonbinary people and their parents by text "
                           "and phone (not a crisis line). Text START to "
                           "833-435-7798 (TransHelpline) to opt in.",
            "website": "https://standwithtrans.org/ally-parents/",
            "phone": "833-435-7798",
            "service_area": Flow(kind="national"),
            "sources": [source_id],
            "verified": Flow(on=today(), method="scrape"),
        },
    ]
    if not org_id:  # CenterLink record gone — write the umbrella ourselves
        rec = {
            "_state": "mi", "_place_slug": "", "_name": "Stand with Trans",
            "id": ORG_ID,
            "categories": ["trans-services", "family-support", "lgbtq-youth"],
            "description": "Support for trans youth and their families — free "
                           "virtual and Metro Detroit peer support groups for "
                           "teens, young adults, and parents/caregivers, plus "
                           "mental health therapy services and trainings.",
            "address": Flow(street="23332 Farmington Rd #84", city="Farmington",
                            state="mi", zip="48336"),
            "website": "https://standwithtrans.org",
            "phone": "248-907-4853",
            "email": "info@standwithtrans.org",
            "service_area": Flow(kind="national"),
            "sources": [source_id],
            "verified": Flow(on=today(), method="scrape"),
        }
        geoid, _ = places.resolve("mi", "Farmington")
        if geoid:
            rec["place"] = geoid
        orgs.append(rec)

    meetings = group_meetings(places, org_id or ORG_ID, source_id, force)
    meetings += art_meeting(places, org_id or ORG_ID, source_id, force)

    total = len(meetings) + len(orgs)
    print(f"standwithtrans: {len(meetings)} meetings + {len(orgs)} orgs")
    if total < 8:
        raise SystemExit(f"standwithtrans: only {total} records — floor 8; "
                         "site layout changed? aborting")
    replace_records("orgs", source_id, orgs)
    replace_records("meetings", source_id, meetings)


if __name__ == "__main__":
    main(sys.argv[1:])
