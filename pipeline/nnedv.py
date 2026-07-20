"""NNEDV state/territory DV coalition list -> org records (domestic-violence).

Single server-rendered WordPress page: each coalition is a centered <p><strong>
name block tagged with a `jumpa` anchor, followed by a "Website:" line (NBSP
after the label). The anchor ids are shifted/broken on the live page, so the
state is derived from the entry text itself plus a small fallback map. The
Oklahoma entry is not a coalition (it points at the state AG's certified-program
list) and is skipped. Per policy, DV records never carry street addresses —
this page only publishes names and websites anyway.

Usage: python3 -m pipeline.nnedv [--force]
"""
import html
import re
import sys
import unicodedata

from .emit import replace_records, today, write_source
from .util import Flow, SOURCES, fetch

URL = "https://nnedv.org/content/state-u-s-territory-coalitions/"

ENTRY_RE = re.compile(
    r'<a id="[^"]*" class="jumpa"></a>(?P<name>.*?)</strong>'
    r'(?P<rest>.*?)(?=<strong><a id="[^"]*" class="jumpa">|<div class="post-nav|\Z)',
    re.S)
WEBSITE_RE = re.compile(r'Website:\s*<a href="([^"]+)"')

STATE_NAMES = {
    "alabama": "al", "alaska": "ak", "american samoa": "as", "arizona": "az",
    "arkansas": "ar", "california": "ca", "colorado": "co", "connecticut": "ct",
    "delaware": "de", "dc": "dc", "district of columbia": "dc", "florida": "fl",
    "georgia": "ga", "guam": "gu", "hawaii": "hi", "idaho": "id", "illinois": "il",
    "indiana": "in", "iowa": "ia", "kansas": "ks", "kentucky": "ky",
    "louisiana": "la", "maine": "me", "maryland": "md", "massachusetts": "ma",
    "michigan": "mi", "minnesota": "mn", "mississippi": "ms", "missouri": "mo",
    "montana": "mt", "nebraska": "ne", "nevada": "nv", "new hampshire": "nh",
    "new jersey": "nj", "new mexico": "nm", "new york": "ny",
    "north carolina": "nc", "north dakota": "nd", "northern marianas": "mp",
    "northern mariana islands": "mp", "ohio": "oh", "oklahoma": "ok",
    "oregon": "or", "pennsylvania": "pa", "puerto rico": "pr",
    "rhode island": "ri", "south carolina": "sc", "south dakota": "sd",
    "tennessee": "tn", "texas": "tx", "utah": "ut", "vermont": "vt",
    "virgin islands": "vi", "virginia": "va", "washington": "wa",
    "west virginia": "wv", "wisconsin": "wi", "wyoming": "wy",
}

# coalitions whose entry text names no state/territory
FALLBACK_STATES = {
    "coordinadora paz para las mujeres": "pr",  # Puerto Rico
    "zerov": "ky",  # formerly Kentucky Coalition Against Domestic Violence
}


def strip_tags(fragment: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", " ", fragment))


def find_state(text: str) -> str | None:
    """Longest state/territory name mentioned in the entry text wins, so
    'West Virginia' beats 'Virginia' and 'New Mexico' beats nothing."""
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    low = re.sub(r"[^a-z ]+", " ", text.lower())
    low = f" {' '.join(low.split())} "
    best = None
    for name, code in STATE_NAMES.items():
        if f" {name} " in low and (best is None or len(name) > len(best[0])):
            best = (name, code)
    return best[1] if best else None


def main(argv):
    force = "--force" in argv
    cache = SOURCES / "nnedv" / "coalitions.html"
    text = fetch(URL, cache, force=force).read_text()

    source_id = write_source(
        "nnedv", "state-coalitions",
        kind="directory", publisher="NNEDV (National Network to End Domestic Violence)",
        title="State and U.S. Territorial Coalitions",
        url=URL, tier="primary",
    )

    records, seen_states = [], set()
    for m in ENTRY_RE.finditer(text):
        name = strip_tags(m["name"]).strip()
        name = " ".join(name.split())
        if not name or name.lower().startswith("for resources in oklahoma"):
            continue  # Oklahoma has no coalition; the page links the AG list instead
        state = FALLBACK_STATES.get(name.lower()) or find_state(name + " " + strip_tags(m["rest"][:300]))
        if not state:
            raise SystemExit(f"nnedv: no state resolved for coalition {name!r}")
        if state in seen_states:
            raise SystemExit(f"nnedv: two coalitions resolved to state {state!r} ({name!r})")
        seen_states.add(state)
        rec = {
            "_state": state, "_place_slug": "", "_name": name,
            "categories": ["domestic-violence"],
            "service_area": Flow(kind="state", state=state),
        }
        w = WEBSITE_RE.search(m["rest"])
        if w:
            url = w.group(1).strip()
            rec["website"] = url if url.startswith("http") else f"https://{url}"
        rec["sources"] = [source_id]
        rec["verified"] = Flow(on=today(), method="scrape")
        records.append(rec)

    if len(records) < 50:
        raise SystemExit(f"nnedv: only {len(records)} coalitions — expected ~55; aborting")
    replace_records("orgs", source_id, records)


if __name__ == "__main__":
    main(sys.argv[1:])
