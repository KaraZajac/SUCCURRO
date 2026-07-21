"""ACF FVPSA state/territory administrators + tribal grantees -> org
records (domestic-violence).

Two OFVPS-published PDFs (acf.gov challenges non-browser clients —
fetched with BROWSER_UA; cached under sources/acf/fvpsa/):

- State and Territory Administrators List (last updated 05/02/2023,
  linked from the FVPSA formula-grants page): a 3-column table
  (Organization | Address | Website) covering the 50 states + DC + PR +
  USVI (53; the list does not include AS/GU/CNMI). Columns are split at
  blank vertical gutters per page; records are delimited by the
  jurisdiction name that opens every agency name. The address column is
  deliberately not parsed — DV policy keeps these records to name/
  website/service_area (and the PDF publishes no phones).

- FY 2025 FVPSA Tribes & Tribal Organizations grant recipients: 114
  numbered rows (State | Tribe | Award). The award table's 50-char name
  field clips a few long names mid-word ("...RESERVATIO"); the known
  clipped suffixes are completed. Award amounts are not recorded.

DV POLICY — same field allowlist as dvcoalitions: no address fields
ever, org name / description / website / service_area only.

Usage: python3 -m pipeline.fvpsa [--force]
"""
import re
import subprocess
import sys

from .emit import replace_records, today, write_source
from .util import BROWSER_UA, Flow, SOURCES, fetch

ADMIN_URL = ("https://acf.gov/sites/default/files/documents/ofvps/"
             "State%20Administrators%20List%202023.pdf")
TRIBES_URL = ("https://acf.gov/sites/default/files/documents/ofvps/"
              "FY25-FVPSA-Tribes---Tribal-ORGS-Grant-Awards.pdf")

ALLOWED_KEYS = {"_state", "_place_slug", "_name", "categories",
                "description", "phone", "website", "service_area",
                "sources", "verified"}

JURISDICTIONS = {
    "Alabama": "al", "Alaska": "ak", "Arizona": "az", "Arkansas": "ar",
    "California": "ca", "Colorado": "co", "Connecticut": "ct",
    "Delaware": "de", "District of Columbia": "dc", "Florida": "fl",
    "Georgia": "ga", "Hawaii": "hi", "Idaho": "id", "Illinois": "il",
    "Indiana": "in", "Iowa": "ia", "Kansas": "ks", "Kentucky": "ky",
    "Louisiana": "la", "Maine": "me", "Maryland": "md",
    "Massachusetts": "ma", "Michigan": "mi", "Minnesota": "mn",
    "Mississippi": "ms", "Missouri": "mo", "Montana": "mt",
    "Nebraska": "ne", "Nevada": "nv", "New Hampshire": "nh",
    "New Jersey": "nj", "New Mexico": "nm", "New York": "ny",
    "North Carolina": "nc", "North Dakota": "nd", "Ohio": "oh",
    "Oklahoma": "ok", "Oregon": "or", "Pennsylvania": "pa",
    "Puerto Rico": "pr", "Rhode Island": "ri", "South Carolina": "sc",
    "South Dakota": "sd", "Tennessee": "tn", "Texas": "tx", "Utah": "ut",
    "Vermont": "vt", "Virgin Islands": "vi", "Virgin Island": "vi",
    "Virginia": "va", "Washington": "wa", "West Virginia": "wv",
    "Wisconsin": "wi", "Wyoming": "wy",
}
# longest-first so "West Virginia"/"Virgin Island" win over "Virginia"
JURIS_ORDER = sorted(JURISDICTIONS, key=len, reverse=True)

ADMIN_JUNK_RE = re.compile(
    r"Office of Family Violence|Family Violence Prevention and Services"
    r"|Administrators List|acf\.hhs\.gov/ofvps|Last updated"
    r"|^\s*Organization\s+Address\s+Website\s*$")


def pdf_text(url: str, name: str, force: bool) -> str:
    pdf = fetch(url, SOURCES / "acf" / "fvpsa" / name, force=force,
                ua=BROWSER_UA)
    out = subprocess.run(["pdftotext", "-layout", str(pdf), "-"],
                         capture_output=True, text=True)
    if out.returncode != 0:
        raise SystemExit(f"fvpsa: pdftotext failed on {name}: "
                         f"{out.stderr[:200]}")
    return out.stdout


def column_spans(lines: list[str], min_gap: int = 3) -> list[tuple]:
    """(start, end) spans of the text columns of a page, split at
    vertical all-blank gutters at least min_gap wide."""
    width = max((len(l) for l in lines), default=0)
    occ = [0] * (width + 1)
    for l in lines:
        for i, ch in enumerate(l):
            if ch != " ":
                occ[i] += 1
    gaps, start = [], None
    for i in range(width + 1):
        if occ[i] == 0:
            if start is None:
                start = i
        else:
            if start is not None and i - start >= min_gap:
                gaps.append((start, i))
            start = None
    if start is not None:
        gaps.append((start, width + 1))
    edges = [0]
    for a, b in gaps:
        if a == 0:
            edges[0] = b
        else:
            edges.append(a)
    spans = list(zip(edges, edges[1:] + [width + 1]))
    return [(a, b) for a, b in spans
            if any(l[a:b].strip() for l in lines)]


def jurisdiction_of(text: str) -> str | None:
    for j in JURIS_ORDER:
        if text.startswith(j):
            return j
    return None


def parse_admins(text: str, source_id: str) -> list[dict]:
    """One record per state/territory administrator agency."""
    agencies: dict[str, dict] = {}
    for page in text.split("\f"):
        lines = [l for l in page.splitlines()
                 if l.strip() and not ADMIN_JUNK_RE.search(l)]
        if not lines:
            continue
        spans = column_spans(lines)
        if len(spans) != 3:
            raise SystemExit(f"fvpsa: admin page split into {len(spans)} "
                             "columns (expected 3) — layout changed")
        (o1, o2), _, (w1, w2) = spans  # address column ignored (DV policy)
        cur = None
        for l in lines:
            org = l[o1:o2].strip()
            web = l[w1:w2].strip()
            jur = jurisdiction_of(org)
            if jur:
                if jur == "Virgin Island":
                    jur = "Virgin Islands"
                cur = agencies.setdefault(
                    jur, {"name_parts": [], "web_parts": []})
            if cur is None:
                continue
            if org:
                cur["name_parts"].append(org)
            if web:
                cur["web_parts"].append(web)

    records = []
    for jur, a in agencies.items():
        st = JURISDICTIONS[jur]
        name = " ".join(" ".join(a["name_parts"]).split())
        website = "".join(a["web_parts"]) or None
        if website and not website.lower().startswith("http"):
            print(f"fvpsa: odd website {website!r} for {jur} — dropped")
            website = None
        desc = (f"State administrator of federal Family Violence "
                f"Prevention and Services Act (FVPSA) funds for {jur}: "
                "the agency that administers FVPSA grants supporting "
                "domestic violence shelters and supportive services.")
        rec = {"_state": st, "_place_slug": "", "_name": name,
               "categories": ["domestic-violence"], "description": desc}
        if website:
            rec["website"] = website
        rec["service_area"] = Flow(kind="state", state=st)
        rec["sources"] = [source_id]
        rec["verified"] = Flow(on=today(), method="scrape")
        records.append(rec)
    return records


# clipped-suffix completions for the award table's 50-char name field
TRIBE_CLIPPED = ("Reservation", "Indians", "Nebraska")

TRIBE_ROW_RE = re.compile(
    r"^\s*\d+\s+([A-Z]{2})\s{2,}(.+?)\s{2,}\$[\d,]+\.\d{2}\s*$", re.M)


def tribe_name(raw: str) -> str:
    name = " ".join(raw.replace("`", "'").split())
    name = re.sub(r",?\s*\(ONAP\)$", "", name)  # grant-admin annotation
    clipped = len(raw.strip()) >= 49
    if name.isupper():
        name = name.title()
        name = re.sub(r"(?<!^)\b(Of|The|And|For|In)\b",
                      lambda m: m.group(0).lower(), name)
    if clipped:
        last = name.split()[-1]
        for full in TRIBE_CLIPPED:
            if len(last) >= 5 and full.lower().startswith(last.lower()) \
                    and last.lower() != full.lower():
                name = name[:-len(last)] + full
                print(f"fvpsa: completed clipped name ...{last!r} -> "
                      f"{full!r}")
                break
    return name


def parse_tribes(text: str, source_id: str) -> list[dict]:
    records, seen = [], set()
    for st, raw in TRIBE_ROW_RE.findall(text):
        name = tribe_name(raw)
        key = (st.lower(), name.lower())
        if key in seen:
            continue
        seen.add(key)
        desc = ("Native American tribe or tribal organization receiving "
                "an FY 2025 FVPSA grant for domestic violence shelter "
                "and supportive services.")
        records.append({
            "_state": st.lower(), "_place_slug": "", "_name": name,
            "categories": ["domestic-violence"], "description": desc,
            "sources": [source_id],
            "verified": Flow(on=today(), method="scrape")})
    return records


def main(argv):
    force = "--force" in argv

    admin_sid = write_source(
        "acf", "fvpsa-state-administrators", kind="dataset",
        publisher="ACF Office of Family Violence Prevention and Services",
        title="FVPSA State and Territory Administrators List",
        url=ADMIN_URL, tier="primary",
        notes="Document last updated 05/02/2023; linked from the FVPSA "
              "formula-grants-to-states page. Covers 50 states + DC + PR "
              "+ USVI; AS/GU/CNMI are not in the published list.")
    admins = parse_admins(
        pdf_text(ADMIN_URL, "state-administrators-2023.pdf", force),
        admin_sid)
    if len(admins) < 50:
        raise SystemExit(f"fvpsa: only {len(admins)} administrators — "
                         "floor is 50")

    tribes_sid = write_source(
        "acf", "fvpsa-tribal-grantees-fy2025", kind="dataset",
        publisher="ACF Office of Family Violence Prevention and Services",
        title="FY 2025 FVPSA Tribes and Tribal Organizations grant "
              "recipients", url=TRIBES_URL, tier="primary")
    tribes = parse_tribes(
        pdf_text(TRIBES_URL, "tribal-grantees-fy2025.pdf", force),
        tribes_sid)
    if len(tribes) < 100:
        raise SystemExit(f"fvpsa: only {len(tribes)} tribal grantees — "
                         "floor is 100")

    for group in (admins, tribes):
        for rec in group:
            extra = set(rec) - ALLOWED_KEYS
            assert not extra, f"fvpsa: disallowed fields {extra} on " \
                              f"{rec['_name']}"
            assert not re.search(r"\b\d{5}(?:-\d{4})?\b|\bP\.?O\.? ?Box\b",
                                 rec.get("description", ""))
    replace_records("orgs", admin_sid, admins)
    replace_records("orgs", tribes_sid, tribes)
    print(f"fvpsa: {len(admins)} administrators, {len(tribes)} tribal "
          "grantees")


if __name__ == "__main__":
    main(sys.argv[1:])
