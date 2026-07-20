"""NAMI National Warmline Directory (PDF) -> org records
(mental-health, peer-support).

Warmlines are peer-run, explicitly NON-crisis phone lines, so records do
NOT carry the crisis-hotline category; every description opens with
"Warmline (non-crisis peer support)".

The PDF is a layout table (State | Warmline | Phone | Hours | Spanish |
Chat/Text) plus two closing "National Support Lines" pages (Population |
Line + description | Phone | Hours | Spanish | Chat/Text). It is parsed
from `pdftotext -layout` output: rows are blank-line-separated blocks,
and each line's cells (2+ space splits) are assigned to the column whose
header-label center is nearest. National entries are emitted under the
`us` tree with service_area national; everything else gets its state
(county-specific lines noted in the description).

Usage: python3 -m pipeline.warmlines [--force]
"""
import re
import subprocess
import sys

from .emit import replace_records, today, write_source
from .util import Flow, SOURCES, fetch

URL = ("https://www.nami.org/wp-content/uploads/2026/03/"
       "Warmline-Directory_as-of-March-9-2026.pdf")

PHONE_RE = re.compile(r"\(?\b(\d{3})\)?[-. ]\s*(\d{3})[-. ](\d{4})\b")
CELL_RE = re.compile(r"\S(?:.*?\S)?(?=\s{2,}|\s*$)")
STATES = set("""al ak az ar ca co ct de dc fl ga hi id il in ia ks ky la me md
ma mi mn ms mo mt ne nv nh nj nm ny nc nd oh ok or pa pr ri sc sd tn tx ut vt
va wa wv wi wy""".split())

FOOTER_RE = re.compile(
    r"Blue boxes|NAMI National Warmline Directory|\(as of March|"
    r"National Support Lines|^\s*\d+\s*$")


def cells(line: str) -> list[tuple[float, str]]:
    """(center-offset, text) for each 2+-space-separated cell."""
    out = []
    for m in CELL_RE.finditer(line):
        out.append((m.start() + (m.end() - m.start()) / 2, m.group(0)))
    return out


def columnize(block: list[str], centers: list[float]) -> list[list[tuple[int, str]]]:
    """Assign every cell to the nearest column as (line-idx, text)."""
    cols: list[list[tuple[int, str]]] = [[] for _ in centers]
    for li, line in enumerate(block):
        for center, text in cells(line):
            idx = min(range(len(centers)), key=lambda i: abs(centers[i] - center))
            cols[idx].append((li, text))
    return cols


def col_text(col, lo=0, hi=10 ** 9) -> str:
    return " ".join(t for li, t in col if lo <= li < hi)


def phones_of(text: str) -> list[str]:
    return [f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
            for m in PHONE_RE.finditer(text)]


def blocks_of(lines: list[str]) -> list[list[str]]:
    blocks, cur = [], []
    for line in lines:
        if line.strip():
            cur.append(line)
        elif cur:
            blocks.append(cur)
            cur = []
    if cur:
        blocks.append(cur)
    return blocks


def split_bounds(anchor_lines: list[int], n_lines: int) -> list[tuple[int, int]]:
    """Row (start, end) ranges for a block with one anchor line per row
    (adjacent anchor lines collapse into one row); rows are vertically
    centered, so the cut between rows falls midway between anchors."""
    groups: list[list[int]] = []
    for li in anchor_lines:
        if groups and li - groups[-1][-1] <= 1:
            groups[-1].append(li)
        else:
            groups.append([li])
    bounds = []
    for k, g in enumerate(groups):
        start = 0 if k == 0 else (groups[k - 1][-1] + g[0] + 1) // 2
        end = n_lines if k == len(groups) - 1 else \
            (g[-1] + groups[k + 1][0] + 1) // 2
        bounds.append((start, end))
    return bounds


def header_centers(page: str) -> tuple[list[float], int] | None:
    """Column-label centers for a state page. The Chat/Text label
    sometimes wraps onto its own line; it falls back to a fixed offset
    right of Spanish."""
    lines = page.split("\n")
    for i, line in enumerate(lines):
        if all(k in line for k in ("State", "Warmline", "Phone Number",
                                   "Hours", "Spanish")):
            centers = []
            for lab in ("State", "Warmline", "Phone Number",
                        "Hours of Operation", "Spanish"):
                j = line.find(lab.split()[0])
                centers.append(j + len(lab) / 2)
            chat = -1
            for near in lines[max(0, i - 2): i + 3]:
                chat = near.find("Chat")
                if chat >= 0:
                    chat += len("Chat/Text") / 2
                    break
            centers.append(chat if chat >= 0 else centers[-1] + 12)
            return centers, i
    return None


def parse_state_page(page: str, source_id: str, skipped: list) -> list[dict]:
    head = header_centers(page)
    if not head:
        return []
    centers, hi = head
    lines = [l for l in page.split("\n")[hi + 1:] if not FOOTER_RE.search(l)]
    records = []
    for block in blocks_of(lines):
        anchors = [li for li, l in enumerate(block)
                   if re.match(r"^\s{0,4}[A-Z]{2}(\s|$)", l)]
        for lo, hi2 in split_bounds(anchors, len(block)) if anchors else []:
            rec = state_row(block[lo:hi2], centers, source_id, skipped)
            if rec:
                records.append(rec)
    return records


def state_row(row_lines: list[str], centers, source_id: str,
              skipped: list) -> dict | None:
    st_col, name_col, phone_col, hours_col, es_col, chat_col = \
        columnize(row_lines, centers)
    state = next((t.strip().lower() for _, t in st_col
                  if re.fullmatch(r"[A-Z]{2}", t.strip())), None)
    name = col_text(name_col)
    if not state or state not in STATES or not name:
        if col_text(st_col) or name:
            skipped.append((col_text(st_col) + " " + name)[:60])
        return None
    serves_m = re.search(r"\(serves residents of ([^)]+)\)", name)
    name = re.sub(r"\s*\(serves residents of [^)]+\)", "", name).strip()
    phones = phones_of(col_text(phone_col))
    if not phones:
        skipped.append(f"{state}: {name} (no phone)")
        return None

    desc = ["Warmline (non-crisis peer support)."]
    area = Flow(kind="state", state=state)
    if serves_m:
        serves = serves_m.group(1).strip()
        cm = re.fullmatch(r"([A-Za-z .]+) County(?:, [A-Z]{2})?", serves)
        if cm:
            area = Flow(kind="county", name=cm.group(1).strip(), state=state)
        elif serves.lower() != state:
            area = None  # sub-state locality — context lives in the description
        if serves.lower() != state:
            desc.append(f"Serves residents of {serves}.")
    hours = col_text(hours_col)
    if hours:
        desc.append(f"Hours: {hours}.")
    if len(phones) > 1:
        desc.append(f"Additional number: {phones[1]}.")
    if "yes" in col_text(es_col).lower():
        desc.append("Spanish-language support available.")
    chat = col_text(chat_col)
    if chat:
        desc.append(f"{chat} support available."
                    if chat.lower() in ("chat", "text", "chat & text")
                    else f"Chat/text: {chat}.")

    rec = {
        "_state": state, "_place_slug": "", "_name": name,
        "categories": ["mental-health", "peer-support"],
        "description": " ".join(" ".join(desc).split()),
        "phone": phones[0],
    }
    if area:
        rec["service_area"] = area
    rec["sources"] = [source_id]
    rec["verified"] = Flow(on=today(), method="scrape")
    return rec


def national_centers(page: str) -> tuple[list[float], int] | None:
    """Column-label centers for a National Support Lines page (only the
    first such page carries the header; callers reuse the centers)."""
    lines = page.split("\n")
    for i, line in enumerate(lines):
        if "Peer-Support Line" in line and "Phone Number" in line:
            centers = []
            for lab in ("Subject", "Peer-Support Line / Description",
                        "Phone Number", "Hours of Operation", "Spanish",
                        "Chat/Text"):
                j = line.find(lab.split()[0])
                centers.append(j + len(lab) / 2)
            return centers, i
    return None


def parse_national_page(page: str, centers, source_id: str,
                        skipped: list) -> list[dict]:
    """Rows are anchored on the description cell that starts with
    "Provides"; the cell just above it is the line's name."""
    head = national_centers(page)
    if head:
        centers, hi = head
        lines = page.split("\n")[hi + 1:]
    else:
        lines = page.split("\n")
    lines = [l for l in lines if not FOOTER_RE.search(l)
             and "Population /" not in l and l.strip() != "Subject"]
    records = []
    for block in blocks_of(lines):
        pop_col, body_col, phone_col, hours_col, es_col, chat_col = \
            columnize(block, centers)
        starts = [k for k, (_, t) in enumerate(body_col)
                  if t.startswith("Provides")]
        for n, k in enumerate(starts):
            if k == 0:
                skipped.append(f"national: nameless row: {body_col[k][1][:40]}")
                continue
            name_li, name = body_col[k - 1]
            lo = name_li
            hi2 = body_col[starts[n + 1] - 1][0] if n + 1 < len(starts) \
                else 10 ** 9
            about = " ".join(t for li, t in body_col
                             if lo <= li < hi2 and (li, t) != (name_li, name))
            phones = phones_of(col_text(phone_col, lo, hi2))
            if not phones:
                skipped.append(f"national: {name} (no phone)")
                continue
            pop = " ".join(col_text(pop_col, lo, hi2).split())
            desc = ["National peer-support line (listed in NAMI's warmline "
                    "directory)."]
            if pop:
                desc.append(f"Population: {pop}.")
            if about:
                desc.append(about.rstrip(".") + ".")
            hours = col_text(hours_col, lo, hi2)
            if hours:
                desc.append(f"Hours: {hours}.")
            if "yes" in col_text(es_col, lo, hi2).lower():
                desc.append("Spanish-language support available.")
            chat = col_text(chat_col, lo, hi2)
            if chat:
                desc.append(f"Chat/text: {chat}.")
            records.append({
                "_state": "us", "_place_slug": "", "_name": name,
                "categories": ["mental-health", "peer-support"],
                "description": " ".join(" ".join(desc).split()),
                "phone": phones[0],
                "service_area": Flow(kind="national"),
                "sources": [source_id],
                "verified": Flow(on=today(), method="scrape"),
            })
    return records


def main(argv):
    force = "--force" in argv
    pdf = fetch(URL, SOURCES / "nami" / "warmline-directory-2026-03-09.pdf",
                force=force)
    text = subprocess.run(["pdftotext", "-layout", str(pdf), "-"],
                          capture_output=True, text=True, check=True).stdout

    source_id = write_source(
        "nami", "warmline-directory",
        kind="directory", publisher="NAMI (National Alliance on Mental Illness)",
        title="NAMI National Warmline Directory (as of March 9, 2026)",
        url=URL, published_on="2026-03-09", tier="secondary",
    )

    records, skipped, nat_centers = [], [], None
    for page in text.split("\f"):
        if "National Support Lines" in page:
            head = national_centers(page)
            if head:
                nat_centers = head[0]
            if not nat_centers:
                raise SystemExit("warmlines: national page without a header "
                                 "and no centers carried over")
            records += parse_national_page(page, nat_centers, source_id,
                                           skipped)
        else:
            records += parse_state_page(page, source_id, skipped)

    for line in skipped:
        print(f"warmlines: skipped: {line}")
    if len(records) < 80:
        raise SystemExit(f"warmlines: only {len(records)} lines — expected 80+")
    replace_records("orgs", source_id, records)


if __name__ == "__main__":
    main(sys.argv[1:])
