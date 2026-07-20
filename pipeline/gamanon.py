"""Gam-Anon (families of compulsive gamblers) -> meeting records.

gam-anon.org's US directory is one server-rendered Joomla page
(/meeting-directory/us-meetings, ~77 entries): state/area heading_group
sections each holding latestnews-item blocks with the meeting name, day
(jfield_1), time (jfield_27), timezone (jfield_31), language (jfield_34),
free-text focus lines, and a single comma-separated venue string
(jfield_14: "Venue Name, street, City, ST, zip" with plenty of variation —
missing zips, "AZ 85741" fused tokens, trailing commas). The page carries
a limitstart form but lists everything at once. Meetings whose focus text
says HYBRID become format: hybrid; everything else is in-person. State
comes from the venue string, falling back to the section heading
("CA - Los Angeles Area", "New York - Brooklyn", plain "Arizona").

Usage: python3 -m pipeline.gamanon [--force]
"""
import html as htmllib
import re
import sys

from .bmlt import norm_state
from .emit import Places, replace_records, today, write_source
from .util import Flow, SOURCES, fetch

URL = "https://gam-anon.org/meeting-directory/us-meetings"

DAYS = {"sunday": "sun", "monday": "mon", "tuesday": "tue", "wednesday": "wed",
        "thursday": "thu", "friday": "fri", "saturday": "sat"}
LANGS = {"english": "en", "spanish": "es", "french": "fr"}
FOCUS_TYPES = [
    (re.compile(r"combined", re.I), "combined-gam-anon-ga"),
    (re.compile(r"step", re.I), "step"),
    (re.compile(r"parent", re.I), "parents"),
    (re.compile(r"adult children", re.I), "adult-children"),
    (re.compile(r"newcomer", re.I), "newcomer"),
    (re.compile(r"gam-?a-?teen", re.I), "gam-a-teen"),
]

ITEM_RE = re.compile(r'<div class="latestnews-item id-(\d+)[^"]*">(.*?)</dl>', re.S)
HEADING_RE = re.compile(r'<h2 class="heading">([^<]+)</h2>')
NAME_RE = re.compile(r'<a href="([^"]+)"[^>]*>\s*<span>(.*?)</span>', re.S)
FIELD_RE = re.compile(r'detail_jfield_(\d+)\s*"><span class="detail_label">[^<]*'
                      r'</span><span class="detail_data">(.*?)</span>', re.S)
FIELD1_RE = re.compile(r'detail_jfield_(\d+)\s*"><span class="detail_data">(.*?)</span>', re.S)
TIME_RE = re.compile(r"(\d{1,2})(?::(\d{2}))?\s*([AP])\.?M", re.I)


def clean(text: str) -> str:
    return re.sub(r"\s+", " ", htmllib.unescape(re.sub(r"<[^>]+>", " ", text))).strip()


def heading_state(heading: str, by_state):
    lead = re.split(r"\s+-\s+", heading)[0].strip()
    lead = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", lead)  # "SouthDakota"
    return norm_state(lead, by_state)


def parse_venue(raw: str, by_state):
    """'Venue, street, City, ST, zip' (many variants) ->
    (venue_name, street, city, state, zip). A zip is only recognized as the
    final comma token or fused to the state token ("AZ 85741") — a bare
    5-digit match anywhere would eat street numbers like "12835 N. 32 St."."""
    parts = [p.strip(" .") for p in raw.split(",")]
    parts = [p for p in parts if p]
    zipc = None
    if parts and re.fullmatch(r"\d{5}(-\d{4})?", parts[-1]):
        zipc = parts.pop()[:5]
    state_i, st = None, None
    for i in range(len(parts) - 1, -1, -1):
        m = re.fullmatch(r"(.*?)(?:\s+(\d{5})(?:-\d{4})?)?", parts[i])
        cand = norm_state(m.group(1), by_state) if m else None
        if cand:
            state_i, st = i, cand
            if m.group(2):
                zipc = zipc or m.group(2)
            break
    if state_i is None:
        return None, None, None, None, zipc
    city = parts[state_i - 1] if state_i >= 1 else None
    rest = parts[: max(state_i - 1, 0)]
    venue_name = None
    if rest and not rest[0][0].isdigit():
        venue_name = rest.pop(0)
    street = ", ".join(rest) or None
    return venue_name, street, city, st, zipc


def main(argv):
    force = "--force" in argv
    places = Places()

    html = fetch(URL, SOURCES / "gamanon" / "us-meetings.html",
                 force=force).read_text()

    source_id = write_source(
        "gamanon", "us-meeting-directory",
        kind="directory", publisher="Gam-Anon International Service Office",
        title="Gam-Anon US meeting directory",
        url=URL, tier="primary",
    )

    # walk headings and items in document order
    events = []
    for m in HEADING_RE.finditer(html):
        events.append((m.start(), "h", clean(m.group(1))))
    for m in ITEM_RE.finditer(html):
        events.append((m.start(), "i", (m.group(1), m.group(2))))
    events.sort(key=lambda e: e[0])

    records, seen_exact = [], set()
    skips: dict[str, int] = {}
    section = None
    for _, kind, payload in events:
        if kind == "h":
            section = payload
            continue
        item_id, body = payload
        nm = NAME_RE.search(body)
        name = clean(nm.group(2)) if nm else ""
        fields = {}
        for fid, val in FIELD_RE.findall(body) + FIELD1_RE.findall(body):
            fields.setdefault(fid, clean(val))
        day = DAYS.get((fields.get("1") or "").lower())
        tm = TIME_RE.search(fields.get("27") or "")
        if not name or not day or not tm:
            skips["no name/day/time"] = skips.get("no name/day/time", 0) + 1
            continue
        h = int(tm[1]) % 12 + (12 if tm[3].upper() == "P" else 0)
        time = f"{h:02d}:{tm[2] or '00'}"

        venue_raw = fields.get("14") or ""
        venue_name, street, city, st, zipc = parse_venue(venue_raw, places.by_state)
        if not st:
            st = heading_state(section or "", places.by_state)
        if not st:
            skips["no state"] = skips.get("no state", 0) + 1
            continue

        other_text = " ".join(v for k, v in fields.items()
                              if k not in ("1", "27", "31", "34", "14"))
        fmt = "hybrid" if re.search(r"hybrid", other_text + name, re.I) else "in-person"

        rec = {
            "_state": st, "_place_slug": "online", "_name": name,
            "program": "gam-anon",
            "categories": ["recovery-meeting", "family-support"],
            "schedule": [Flow(day=day, time=time)],
            "format": fmt,
        }
        types = [token for pat, token in FOCUS_TYPES if pat.search(other_text)]
        if types:
            rec["types"] = types

        geoid, place_slug = places.resolve(st, city or "")
        rec["_place_slug"] = place_slug
        if venue_name:
            rec["venue_name"] = venue_name
        if city:
            venue = {"street": street, "city": city, "state": st}
            if zipc:
                venue["zip"] = zipc
            rec["venue"] = Flow({k: v for k, v in venue.items() if v})
        if geoid:
            rec["place"] = geoid

        notes = clean(other_text)
        if notes and len(notes) <= 400:
            rec["notes"] = notes
        code = LANGS.get((fields.get("34") or "").lower())
        if code:
            rec["languages"] = [code]

        rec["external_ids"] = Flow(gamanon=item_id)
        if nm:
            rec["url"] = "https://gam-anon.org" + nm.group(1)
        rec["sources"] = [source_id]
        rec["verified"] = Flow(on=today(), method="scrape")

        exact = (name.lower(), day, time, st, rec["_place_slug"])
        if exact in seen_exact:
            continue
        seen_exact.add(exact)
        records.append(rec)

    print(f"gamanon: kept {len(records)}; skips: {skips}")
    if len(records) < 50:
        raise SystemExit(f"gamanon: only {len(records)} meetings — expected 50+; aborting")
    replace_records("meetings", source_id, records)


if __name__ == "__main__":
    main(sys.argv[1:])
