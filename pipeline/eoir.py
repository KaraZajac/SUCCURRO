"""DOJ EOIR pro bono legal service provider list -> org records (legal-aid).

Quarterly PDF, providers grouped by immigration court, two columns per page.
Plain reading-order pdftotext merges the columns mid-line whenever text on the
same baseline touches, gluing bullet text and page headers onto provider
names — so this parser uses `pdftotext -layout` and splits each page's two
columns at the modal indent of right-column lines, reconstructing clean
per-column text.

Within a column: a provider's name line carries a trailing marker
(* nonprofit, ** referral service, *** private attorney; *** entries are
skipped — orgs only), long names wrap with the marker on the last fragment
(joined by walking back), and the body holds street lines, "City, ST ZIP",
"Tel:", email and website lines plus service bullets. Providers repeat under
many courts (with per-court phones); records dedupe by normalized name, first
occurrence wins, state from the provider's own address (court state as
fallback). PDF cached under sources/eoir/; conversion via pdftotext.

Usage: python3 -m pipeline.eoir [--force]
"""
import re
import subprocess
import sys
from collections import Counter

from .emit import Places, norm, replace_records, today, write_source
from .util import Flow, SOURCES, fetch

URL = "https://www.justice.gov/eoir/file/probonofulllist/dl"

MARKER_RE = re.compile(r"^(?P<name>.+?)\s*(?P<stars>\*{1,3})$")
CITY_ST_ZIP_RE = re.compile(r"^(?P<city>.+?),\s*(?P<state>[A-Z]{2})\.?\s+(?P<zip>\d{5})(-\d{4})?$")
TEL_RE = re.compile(r"^Tel:?\s*(.+)$", re.I)
EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")
WEB_RE = re.compile(r"^(https?://|www\.)\S+$", re.I)
HEADING_RE = re.compile(
    r"(Immigration Courts?( Juvenile Docket)?|Hearing Location( Juvenile Docket)?"
    r"|Residential Center)(\s*\(page[^)]*\))?$")

STATE_NAMES = {
    "alabama": "al", "alaska": "ak", "arizona": "az", "arkansas": "ar",
    "california": "ca", "colorado": "co", "connecticut": "ct", "delaware": "de",
    "district of columbia": "dc", "florida": "fl", "georgia": "ga", "hawaii": "hi",
    "idaho": "id", "illinois": "il", "indiana": "in", "iowa": "ia", "kansas": "ks",
    "kentucky": "ky", "louisiana": "la", "maine": "me", "maryland": "md",
    "massachusetts": "ma", "michigan": "mi", "minnesota": "mn", "mississippi": "ms",
    "missouri": "mo", "montana": "mt", "nebraska": "ne", "nevada": "nv",
    "new hampshire": "nh", "new jersey": "nj", "new mexico": "nm", "new york": "ny",
    "north carolina": "nc", "north dakota": "nd", "ohio": "oh", "oklahoma": "ok",
    "oregon": "or", "pennsylvania": "pa", "puerto rico": "pr", "rhode island": "ri",
    "south carolina": "sc", "south dakota": "sd", "tennessee": "tn", "texas": "tx",
    "utah": "ut", "vermont": "vt", "virginia": "va", "washington": "wa",
    "west virginia": "wv", "wisconsin": "wi", "wyoming": "wy",
}
COURT_LOC_RE = re.compile(
    r"^[A-Za-z .()&/-]+,\s*(" + "|".join(n.title() for n in STATE_NAMES) + r")\b")


def norm_phone(raw: str) -> str | None:
    m = re.search(r"\(?(\d{3})\)?[\s./-]{0,3}(\d{3})[\s./-]{0,3}(\d{4})", raw or "")
    return f"{m.group(1)}-{m.group(2)}-{m.group(3)}" if m else None


def title_ratio(name: str) -> float:
    alpha = [w for w in (w.lstrip("(\"'") for w in name.split()) if w[:1].isalpha()]
    return sum(1 for w in alpha if w[0].isupper()) / len(alpha) if alpha else 0.0


def find_gutter(lines: list[str]) -> int | None:
    """Column boundary of a two-column page: the split position (within the
    plausible band) that puts text on its right for the most lines while no
    word straddles it. Right-column indents vary a couple of chars page to
    page (and even block to block), so this scores every candidate instead
    of trusting indent frequencies."""
    best, best_score = None, 3  # demand a real column: at least a few clean lines
    for c in range(40, 86):
        crossings = right = 0
        for l in lines:
            if len(l) > c and l[c:].strip():
                if l[c - 1] != " " or (c >= 2 and l[c - 2] != " "):
                    crossings += 1  # a word (or single space) spans the boundary
                else:
                    right += 1
        # long left-column lines legitimately graze the gutter on dense pages,
        # so crossings are penalized, not disqualifying
        score = right - 2 * crossings
        if score > best_score:  # strict: ties keep the leftmost candidate
            best, best_score = c, score
    if best is None:
        return None
    # snap to the exact right-column start: leftmost text among clean right
    # lines (a leftmost-tie split can otherwise shave the left column's tail)
    starts = [c for l in lines
              if len(l) > best and l[best:].strip()
              and l[best - 1] == " " and l[best - 2] == " "
              for c in [best + len(l[best:]) - len(l[best:].lstrip())]]
    return min(starts) if starts else best


def column_lines(layout_text: str):
    """Reconstruct column-ordered lines from `pdftotext -layout` output:
    per page, drop the header boilerplate and centered court headings, find
    the right column's modal indent, and emit left-column then right-column
    lines (stripped; blanks kept as entry separators)."""
    for page in layout_text.split("\f"):
        if "Table of Contents" in page:
            continue
        kept = []
        for ln in page.splitlines():
            s = ln.strip()
            if s and ("List of Pro Bono Legal Service Providers" in s
                      or "justice.gov/eoir" in s
                      or s.startswith(("* Non-Profit", "** Referral", "*** Private"))):
                continue
            indent = len(ln) - len(ln.lstrip())
            if s and indent >= 10 and HEADING_RE.search(s):
                continue  # centered court heading (may straddle both columns)
            kept.append(ln)
        split = find_gutter(kept)
        if split:
            yield from (l[:split].strip() for l in kept)
            yield ""
            yield from (l[split:].strip() for l in kept)
        else:
            yield from (l.strip() for l in kept)
        yield ""


def is_name_fragment(line: str) -> bool:
    """Leading fragment of a wrapped provider name (walk-back join)?"""
    if not line or line.startswith("•"):
        return False
    if (MARKER_RE.match(line) or COURT_LOC_RE.match(line) or CITY_ST_ZIP_RE.match(line)
            or TEL_RE.match(line) or EMAIL_RE.match(line) or WEB_RE.match(line)):
        return False
    if re.search(r"\d|\(page|\((ICE|BOP|DOD)\)", line):
        return False
    if re.search(r"Immigration Court|Hearing Location|Juvenile Docket|Residential Center",
                 line):
        return False
    if line.endswith(" and") or re.search(r", [A-Z]{2}\b(?![a-z])", line):
        return False  # facility/venue list lines ("... Facility, MA and")
    if line.count(",") >= 2:
        return False  # county/venue enumerations, not name fragments
    return title_ratio(line) >= 0.6


def looks_clean(name: str) -> bool:
    return (len(name) >= 4 and (name[:1].isalnum() or name[:1] == "(")
            and not name[:1].islower()
            and not re.search(r"[*•:]|\(page|\d", name)
            and not re.search(r"Immigration Court|Hearing Location", name)
            and title_ratio(name) >= 0.6)


def parse_providers(lines: list[str]):
    """Yield (name, stars, body, court_state) per provider occurrence."""
    court_state = None
    for i, ln in enumerate(lines):
        loc = COURT_LOC_RE.match(ln)
        if loc and not MARKER_RE.match(ln):
            court_state = STATE_NAMES[loc.group(1).lower()]
            continue
        m = MARKER_RE.match(ln)
        if not m or ln.startswith("•"):
            continue
        name, stars = m["name"].strip(), len(m["stars"])
        j = i - 1
        while j >= 0 and is_name_fragment(lines[j]):
            name = f"{lines[j]} {name}"
            j -= 1
        # a left-column bullet grazing the gutter can leave its last word (a
        # state name, e.g. "... and South Alabama") glued before the org name;
        # a single-word state that isn't this court's own state is that junk
        first, _, rest = name.partition(" ")
        code = STATE_NAMES.get(first.lower())
        if code and code != court_state and rest[:1].isupper():
            name = rest
        body = []
        for nxt in lines[i + 1:]:
            if MARKER_RE.match(nxt) or (COURT_LOC_RE.match(nxt) and "Tel" not in nxt):
                break
            body.append(nxt)
        yield name, stars, body, court_state


def main(argv):
    force = "--force" in argv
    places = Places()
    pdf = fetch(URL, SOURCES / "eoir" / "probono-full-list.pdf", force=force)
    txt = pdf.with_suffix(".txt")
    if force or not txt.exists():
        subprocess.run(["pdftotext", "-layout", str(pdf), str(txt)], check=True)

    source_id = write_source(
        "eoir", "pro-bono-providers",
        kind="dataset",
        publisher="U.S. Department of Justice, Executive Office for Immigration Review",
        title="List of Pro Bono Legal Service Providers (full list)",
        url=URL, tier="primary",
    )

    lines = list(column_lines(txt.read_text()))
    providers = list(parse_providers(lines))
    # When one candidate name is the strict tail of another, one of the two is
    # an artifact — either a truncated/wrap fragment ("Cornelia Law Center" vs
    # "Casa Cornelia Law Center") or a junk-prefixed merge ("Court California
    # Immigration Project"). Artifacts appear on one page; the real form
    # repeats across courts, so the rarer of the pair is dropped.
    counts = Counter(n for n, _, _, _ in providers if looks_clean(n))
    phones: dict[str, set] = {}
    for n, _, body, _ in providers:
        for bln in body:
            t = TEL_RE.match(bln)
            if t:
                p = norm_phone(t.group(1))
                if p:
                    phones.setdefault(n, set()).add(p)
    drop = set()
    for l in counts:
        for s in counts:
            if l == s or len(l) <= len(s) or not l.endswith(s):
                continue
            boundary = l[-len(s) - 1]
            if boundary != " ":
                drop.add(s)  # mid-word truncation ("S (Pennsylvania)")
            elif l[-len(s) - 2] == "," or re.match(r"(Inc|LLC|Corp)\b", s):
                drop.add(s)  # continuation fragment of l's own name
            elif re.search(r"(Courts?|Docket|Location)$", l[: -len(s) - 1].strip()):
                drop.add(l)  # court-heading text glued onto the name
            elif (phones.get(s) and phones.get(l)
                  and not phones[s] & phones[l]):
                pass  # distinct phone numbers: two genuinely different orgs
            elif counts[s] != counts[l]:
                drop.add(s if counts[s] < counts[l] else l)
            else:
                drop.add(s)  # tie: keep the fuller form

    seen: dict[str, dict] = {}
    skipped_attorneys, skipped_junk = 0, []
    for name, stars, body, court_state in providers:
        if stars == 3:  # private attorney — orgs only
            skipped_attorneys += 1
            continue
        if not looks_clean(name) or name in drop:
            skipped_junk.append(name)
            continue
        key = norm(name)
        if not key or key in seen:
            continue
        rec = {"_place_slug": "", "_name": name,
               "categories": ["legal-aid", "immigration-legal"]}
        state, addr, street = None, None, []
        for bln in body:
            if not bln or bln.startswith("•"):
                continue
            csz = CITY_ST_ZIP_RE.match(bln)
            if csz and addr is None:
                state = csz["state"].lower()
                addr = {"city": csz["city"], "state": state, "zip": csz["zip"]}
                if street:
                    addr = {"street": ", ".join(street), **addr}
                continue
            t = TEL_RE.match(bln)
            if t and "phone" not in rec:
                phone = norm_phone(t.group(1))
                if phone:
                    rec["phone"] = phone
                continue
            if EMAIL_RE.match(bln) and "email" not in rec:
                rec["email"] = bln
                continue
            if WEB_RE.match(bln) and "website" not in rec:
                url = bln.rstrip(",;")
                rec["website"] = url if url.lower().startswith("http") else f"https://{url}"
                continue
            if addr is None:
                street.append(bln)
        state = state or court_state
        if not state:
            continue
        rec["_state"] = state
        if addr:
            rec["address"] = Flow(addr)
            geoid, _ = places.resolve(state, addr["city"])
            if geoid:
                rec["place"] = geoid
        rec["sources"] = [source_id]
        rec["verified"] = Flow(on=today(), method="scrape")
        seen[key] = rec

    records = list(seen.values())
    if skipped_attorneys:
        print(f"skipped {skipped_attorneys} private-attorney entries")
    if skipped_junk:
        print(f"skipped {len(skipped_junk)} unparseable name lines: {skipped_junk[:6]}...")
    if len(records) < 100:
        raise SystemExit(f"eoir: only {len(records)} provider orgs — expected ~130; aborting")
    replace_records("orgs", source_id, records)


if __name__ == "__main__":
    main(sys.argv[1:])
