"""National MS Society self-help groups -> meeting records (health/peer-support).

nationalmssociety.org is a Salesforce Experience Cloud (LWR) SPA; detail pages
render client-side, but everything needed is reachable without a browser
(captured with Playwright, 2026-07):

- The SPA shell HTML (any page, ~2 MB) embeds the full route manifest:
  every program/event page as {devName, label, path, view}. Self-help groups
  are the ~239 routes whose label/slug mentions "self-help"/"SHG" under
  /how-you-can-help/get-involved/calendar-of-all-programs-and-events/<slug>.
- Page content lives in a *public* Sanity dataset (project y936aps5, dataset
  production). One GROQ query returns every event page (_id prefix
  "eventPage", _type contentPage) with its dereferenced textBlock content —
  free-text lines labeled "Audience:", "Location:", "Day:", "Time:".
- Route -> Sanity doc is matched on normalized name/SEO-title/slug. For the
  ~10% whose CMS name drifted from the route label, the shell also lists every
  LWR view-resource URL (/webruntime/view/<hash>/prod/en-US/<view>_view); the
  view JS carries the page's sanityPageId, joining route to doc exactly.

Schedules are free text but highly regular ("2nd Saturday of each month",
"6-7:30 p.m. ET"). Day+time are parsed into schedule entries with the
recurrence phrase kept as a note; groups whose day/time can't be parsed
(mostly "contact group leader") are skipped and counted. Online-only groups
shard under us/online. Pages carry no coordinates; in-person records get
place FKs via city resolution but no geo — the validator soft-finds that.

Usage: python3 -m pipeline.mssociety [--force]
"""
import json
import re
import sys
from collections import Counter
from urllib.parse import urlencode

from .bmlt import norm_state
from .emit import Places, replace_records, today, write_source
from .util import BROWSER_UA, Flow, SOURCES, fetch

SITE = "https://www.nationalmssociety.org"
CAL_PATH = "/how-you-can-help/get-involved/calendar-of-all-programs-and-events"
SANITY = "https://y936aps5.apicdn.sanity.io/v2021-10-21/data/query/production"

# every event page with its dereferenced text content, one query
GROQ = ('*[_id match "eventPage*"]{_id, name, '
        '"title": SEOFields.seoTitle[_key=="english"][0].value, '
        '"blocks": contentBlocks[]->{_id, _type, '
        '"textBody": textBody[_key=="english"][0].value}}')

ROUTE_LABEL_RE = re.compile(r'"label":"((?:[^"\\]|\\.)*)"')
ROUTE_PATH_RE = re.compile(rf'"path":"{re.escape(CAL_PATH)}/([a-z0-9-]+)"')
ROUTE_VIEW_RE = re.compile(r'"view":"([A-Za-z0-9_]+)"')
VIEW_URL_RE = re.compile(r"/webruntime/view/([a-z0-9]+)/prod/en-US/([A-Za-z0-9_]+)_view")
SELF_HELP_RE = re.compile(r"self.?help|(^|[^a-z])shg([^a-z]|$)", re.I)
CONTENT_ID_RE = re.compile(r'sanityContentId:"([0-9a-f]{32})"')

DAYWORD_RE = re.compile(r"\b(mon|tues|wednes|thurs|fri|satur|sun)day", re.I)
DAY_TOKEN = {"mon": "mon", "tues": "tue", "wednes": "wed", "thurs": "thu",
             "fri": "fri", "satur": "sat", "sun": "sun"}
TIME_RANGE_RE = re.compile(
    r"(\d{1,2})(?::(\d{2}))?\s*(a\.?m|p\.?m)?\.?\s*(?:[–—-]|to)\s*"
    r"(\d{1,2})(?::(\d{2}))?\s*(a\.?m|p\.?m)\.?", re.I)
TIME_ONE_RE = re.compile(r"(\d{1,2})(?::(\d{2}))?\s*(a\.?m|p\.?m)\.?", re.I)
TZ_RE = re.compile(r"\b([ECMP])T\b")
CITY_LINE_RE = re.compile(r"^([^,]+),\s*([A-Za-z]{2})\s+(\d{5})(?:-\d{4})?$")
LABEL_RE = re.compile(r"^\s*(Audience|Location|Day|Time)\s*:\s*(.*)$", re.S | re.I)


def norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (text or "").lower())


def decode_label(raw: str) -> str:
    raw = raw.replace('\\"', '"').replace("\\/", "/")
    return re.sub(r"\\u([0-9a-fA-F]{4})", lambda m: chr(int(m[1], 16)), raw)


def parse_routes(shell: str):
    """Route manifest entries -> [(slug, label, view)] for self-help groups."""
    out, seen = [], set()
    for chunk in shell.split('"devName":"')[1:]:
        pm = ROUTE_PATH_RE.search(chunk)
        lm = ROUTE_LABEL_RE.search(chunk)
        vm = ROUTE_VIEW_RE.search(chunk)
        if not (pm and lm and vm):
            continue
        slug, label = pm[1], decode_label(lm[1])
        if slug in seen or not SELF_HELP_RE.search(label + " " + slug):
            continue
        seen.add(slug)
        out.append((slug, label, vm[1]))
    return out


def doc_lines(doc: dict):
    """Flatten a Sanity contentPage's text nodes -> list of strings (one per
    paragraph node; addresses keep their internal newlines)."""
    lines = []
    for block in doc.get("blocks") or []:
        for node in (block or {}).get("textBody") or []:
            if node.get("_type") == "textBody":
                text = "".join(c.get("text") or "" for c in node.get("children") or [])
                if text.strip():
                    lines.append(text)
    return lines


def parse_time(text: str):
    """'6-7:30 p.m. ET' -> ('18:00', 90). Start meridiem, when omitted, is
    inferred from the end ('11 a.m.-1 p.m.' starts at 11:00)."""
    m = TIME_RANGE_RE.search(text)
    if m:
        h1, m1, mer1, h2, m2, mer2 = m.groups()
        end = int(h2) % 12 * 60 + int(m2 or 0) + (720 if mer2[0].lower() == "p" else 0)
        mer1 = mer1 or mer2
        start = int(h1) % 12 * 60 + int(m1 or 0) + (720 if mer1[0].lower() == "p" else 0)
        if not m.group(3) and start > end:  # inferred meridiem overshot: 11-1 p.m.
            start -= 720
        dur = end - start
        return f"{start // 60:02d}:{start % 60:02d}", (dur if 0 < dur <= 480 else None)
    m = TIME_ONE_RE.search(text)
    if m:
        h = int(m[1]) % 12 + (12 if m[3][0].lower() == "p" else 0)
        return f"{h:02d}:{m[2] or '00'}", None
    return None, None


def build_record(slug: str, label: str, doc: dict, places: Places, source_id: str):
    fields = {}
    locations = []
    for line in doc_lines(doc):
        m = LABEL_RE.match(line)
        if not m:
            continue
        key, val = m[1].lower(), m[2].strip()
        if not val:
            continue
        if key == "location":
            locations.append(val)
        else:
            fields.setdefault(key, val)

    day_text = fields.get("day", "")
    time_text = fields.get("time", "")
    dm = DAYWORD_RE.search(day_text) or DAYWORD_RE.search(time_text)
    if not dm:
        return None, "no day"
    day = DAY_TOKEN[dm[1].lower()]
    time, duration = parse_time(time_text)
    if not time:
        time, duration = parse_time(day_text)
    if not time:
        return None, "no time"

    online = any("online" in loc.lower() or "virtual" in loc.lower()
                 for loc in locations)
    venue_name = street = city = st = zipc = None
    for loc in locations:
        lines = [l.strip() for l in loc.split("\n") if l.strip()]
        cm = CITY_LINE_RE.match(lines[-1]) if lines else None
        if not cm:
            continue
        st = norm_state(cm[2], places.by_state)
        if st is None:
            return None, "non-US address"
        city, zipc = cm[1].strip(), cm[3]
        rest = lines[:-1]
        if rest and not rest[0][0].isdigit():
            venue_name = rest.pop(0)
        street = ", ".join(rest) or None
        break

    if city and st:
        fmt = "hybrid" if online else "in-person"
    elif online:
        fmt, st = "online", "us"
    else:
        return None, "no location"

    schedule = Flow(day=day, time=time)
    if duration:
        schedule["duration_min"] = duration
    note = re.sub(r"\s+", " ", day_text).strip(" .*")
    if note and not re.fullmatch(r"(?i)every\s+\w+days?", note):
        schedule["note"] = note[:100]
    elif fmt == "online":
        tz = TZ_RE.search(time_text)
        if tz:
            schedule["note"] = tz[0]

    rec = {
        "_state": st, "_place_slug": "online", "_name": label,
        "program": "ms-society",
        "categories": ["health", "peer-support"],
        "schedule": [schedule],
        "format": fmt,
    }
    if fmt != "online":
        geoid, place_slug = places.resolve(st, city)
        rec["_place_slug"] = place_slug
        if venue_name:
            rec["venue_name"] = venue_name
        venue = {"street": street, "city": city, "state": st, "zip": zipc}
        rec["venue"] = Flow({k: v for k, v in venue.items() if v})
        if geoid:
            rec["place"] = geoid
    audience = re.sub(r"\s+", " ", fields.get("audience", "")).strip(" .")
    if audience and len(audience) <= 200:
        rec["notes"] = f"Audience: {audience}"
    rec["url"] = f"{SITE}{CAL_PATH}/{slug}"
    rec["external_ids"] = Flow(ms_society=slug)
    rec["sources"] = [source_id]
    rec["verified"] = Flow(on=today(), method="scrape")
    return rec, None


def main(argv):
    force = "--force" in argv
    places = Places()
    cache_dir = SOURCES / "ms-society"

    shell = fetch(SITE + CAL_PATH, cache_dir / "calendar-shell.html",
                  force=force, ua=BROWSER_UA).read_text(errors="replace")
    routes = parse_routes(shell)
    if len(routes) < 150:
        raise SystemExit(f"mssociety: only {len(routes)} self-help routes in "
                         "the shell manifest — layout changed?")
    print(f"mssociety: {len(routes)} self-help routes in manifest")

    query_url = SANITY + "?" + urlencode({"query": GROQ})
    data = json.loads(fetch(query_url, cache_dir / "eventpages.json",
                            force=force, ua=BROWSER_UA).read_text())
    docs = data.get("result") or []
    if len(docs) < 300:
        raise SystemExit(f"mssociety: Sanity returned only {len(docs)} event "
                         "pages — dataset moved?")
    by_key, by_id = {}, {}
    for d in docs:
        by_id[d["_id"]] = d
        for key in (d.get("name"),
                    (d.get("title") or "").replace(" | National MS Society", "")):
            k = norm(key)
            if k:
                by_key.setdefault(k, d)

    view_hashes = {name: h for h, name in VIEW_URL_RE.findall(shell)}

    source_id = write_source(
        "ms-society", "self-help-groups",
        kind="directory", publisher="National Multiple Sclerosis Society",
        title="National MS Society self-help group pages (program calendar)",
        url=SITE + CAL_PATH, tier="primary",
    )

    # Resolve each route to its Sanity doc. Pages whose CMS name drifted from
    # the route label (and whose docs use bare-UUID ids outside the eventPage*
    # pull) get their textBlock ids read out of the page's LWR view resource;
    # those blocks are then pulled in one batched follow-up query.
    resolved, pending = [], []
    for slug, label, view in routes:
        doc = by_key.get(norm(label)) or by_key.get(norm(slug))
        if doc is not None or view not in view_hashes:
            resolved.append((slug, label, doc))
            continue
        view_url = (f"{SITE}/webruntime/view/{view_hashes[view]}"
                    f"/prod/en-US/{view}_view")
        try:
            js = fetch(view_url, cache_dir / "views" / f"{slug}.js",
                       force=force, ua=BROWSER_UA).read_text(errors="replace")
        except SystemExit as e:
            print(f"WARNING: mssociety {slug}: {e}")
            js = ""
        ids = [f"{u[:8]}-{u[8:12]}-{u[12:16]}-{u[16:20]}-{u[20:]}"
               for u in dict.fromkeys(CONTENT_ID_RE.findall(js))]
        pending.append((slug, label, ids))

    if pending:
        want = sorted({i for _, _, ids in pending for i in ids})
        fb_query = ('*[_id in $ids]{_id, _type, '
                    '"textBody": textBody[_key=="english"][0].value}')
        fb_url = SANITY + "?" + urlencode(
            {"query": fb_query, "$ids": json.dumps(want)})
        fb = json.loads(fetch(fb_url, cache_dir / "fallback-blocks.json",
                              force=force, ua=BROWSER_UA).read_text())
        blocks = {b["_id"]: b for b in fb.get("result") or []}
        for slug, label, ids in pending:
            got = [blocks[i] for i in ids if i in blocks]
            resolved.append((slug, label, {"blocks": got} if got else None))

    records, seen_exact, skips = [], set(), Counter()
    for slug, label, doc in resolved:
        if doc is None:
            skips["no CMS doc"] += 1
            continue
        rec, why = build_record(slug, label, doc, places, source_id)
        if rec is None:
            skips[why] += 1
            continue
        exact = (rec["_name"].lower(), rec["schedule"][0]["day"],
                 rec["schedule"][0]["time"], rec["_state"], rec["_place_slug"])
        if exact in seen_exact:
            skips["duplicate"] += 1
            continue
        seen_exact.add(exact)
        records.append(rec)

    by_fmt = Counter(r["format"] for r in records)
    print(f"mssociety: kept {len(records)} of {len(routes)} routes "
          f"({dict(by_fmt)}); skips: {dict(skips)}")
    if len(records) < 120:
        raise SystemExit(f"mssociety: only {len(records)} meetings — "
                         "expected 150+; aborting")
    replace_records("meetings", source_id, records)


if __name__ == "__main__":
    main(sys.argv[1:])
