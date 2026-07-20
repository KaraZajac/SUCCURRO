"""Postpartum Support International online support groups -> meeting records.

postpartum.net (WordPress, server-rendered) lists ~50 specialized free online
support groups; the index page links every /group/<slug>/ detail page. Each
detail page's entry-content opens with a schedule paragraph — free text, but
regular ("1st Thursday: 8:30-10PM (EST)", "Every Monday at 12PM (EST)/9AM
(PST)"), with <br>-separated lines when a group runs several sessions. Tags
are stripped inline (the CMS sometimes splits words across <strong> spans) and
each line is parsed into a schedule entry; the recurrence phrase is kept as a
note. Groups whose schedule can't be parsed into day+time ("time varies") are
skipped and counted. All groups are online and nationwide: records shard under
us/online. Times are as published (usually ET).

Usage: python3 -m pipeline.psi [--force]
"""
import html as htmllib
import re
import sys
from collections import Counter

from .emit import replace_records, today, write_source
from .util import BROWSER_UA, Flow, SOURCES, fetch

INDEX = "https://postpartum.net/get-help/psi-online-support-meetings/"
GROUP_RE = re.compile(r'href="https://(?:www\.)?postpartum\.net/group/([a-z0-9-]+)/?"')
TITLE_RE = re.compile(r"<h2>(.*?)</h2>", re.S)
# first paragraph of the entry-content div (some pages nest it in layout
# divs and/or lead with a flyer image)
SCHED_P_RE = re.compile(
    r'class="entry-content"[^>]*itemprop[^>]*>'
    r"(?:\s|</?div[^>]*>|<figure.*?</figure>)*<p[^>]*>(.*?)</p>", re.S)
TAG_RE = re.compile(r"<[^>]+>")

DAYWORD_RE = re.compile(r"\b(mon|tues|wednes|thurs|fri|satur|sun)day", re.I)
DAY_TOKEN = {"mon": "mon", "tues": "tue", "wednes": "wed", "thurs": "thu",
             "fri": "fri", "satur": "sat", "sun": "sun"}
TIME_RANGE_RE = re.compile(
    r"(\d{1,2})(?::(\d{2}))?\s*(a\.?m|p\.?m)?\.?\s*(?:[–—-]|to)\s*"
    r"(\d{1,2})(?::(\d{2}))?\s*(a\.?m|p\.?m)\.?", re.I)
TIME_ONE_RE = re.compile(r"(\d{1,2})(?::(\d{2}))?\s*(a\.?m|p\.?m)\b\.?", re.I)
# anything beyond a plain weekly day+time worth preserving verbatim
NOTEWORTHY_RE = re.compile(r"\b(1st|2nd|3rd|4th|5th|last|first|second|third|"
                           r"fourth|twice|and|or|except|varies)\b", re.I)
TZ_RE = re.compile(r"\b([ECMP])[SD]?T\b")


def parse_time(text: str):
    """'8:30-10PM (EST)' -> ('20:30', 90); '3PM (EST)/12PM (PT)' -> ('15:00',
    None). A start meridiem, when omitted, is inferred from the end."""
    m = TIME_RANGE_RE.search(text)
    if m:
        h1, m1, mer1, h2, m2, mer2 = m.groups()
        end = int(h2) % 12 * 60 + int(m2 or 0) + (720 if mer2[0].lower() == "p" else 0)
        mer1 = mer1 or mer2
        start = int(h1) % 12 * 60 + int(m1 or 0) + (720 if mer1[0].lower() == "p" else 0)
        if not m.group(3) and start > end:
            start -= 720
        dur = end - start
        return f"{start // 60:02d}:{start % 60:02d}", (dur if 0 < dur <= 480 else None)
    m = TIME_ONE_RE.search(text)
    if m:
        h = int(m[1]) % 12 + (12 if m[3][0].lower() == "p" else 0)
        return f"{h:02d}:{m[2] or '00'}", None
    return None, None


def parse_schedule(sched_html: str):
    """The schedule paragraph -> ([scheduleEntry, ...], cleaned segments)."""
    segments = []
    for part in re.split(r"<br\s*/?>", sched_html):
        text = htmllib.unescape(TAG_RE.sub("", part))
        text = re.sub(r"\s+", " ", text).strip(" . ")
        if text:
            segments.append(text)
    entries = []
    for seg in segments if len(segments) > 1 else segments or [""]:
        source = seg if len(segments) > 1 else " ".join(segments)
        dm = DAYWORD_RE.search(source)
        time, duration = parse_time(source)
        if not (dm and time):
            continue
        entry = Flow(day=DAY_TOKEN[dm[1].lower()], time=time)
        if duration:
            entry["duration_min"] = duration
        if NOTEWORTHY_RE.search(source):
            entry["note"] = source[:120]
        else:
            tz = TZ_RE.search(source)
            if tz:
                entry["note"] = tz[1] + "T"
        entries.append(entry)
    if not entries and len(segments) > 1:
        # sessions split mid-phrase ("...each month" / "at 9 PM EST"): retry
        # on the joined text as a single entry
        entries, _ = parse_schedule(" ".join(segments))
    return entries, segments


def main(argv):
    force = "--force" in argv
    cache_dir = SOURCES / "psi"

    index = fetch(INDEX, cache_dir / "index.html", force=force,
                  ua=BROWSER_UA).read_text(errors="replace")
    slugs = sorted(set(GROUP_RE.findall(index)) - {"psi-online-support-meetings"})
    if len(slugs) < 40:
        raise SystemExit(f"psi: only {len(slugs)} group pages on the index — "
                         "layout changed?")
    print(f"psi: {len(slugs)} group pages linked from the index")

    source_id = write_source(
        "psi", "online-support-groups",
        kind="directory", publisher="Postpartum Support International",
        title="PSI online support group pages",
        url=INDEX, tier="primary",
    )

    records, seen_exact, skips = [], set(), Counter()
    for slug in slugs:
        url = f"https://postpartum.net/group/{slug}/"
        try:
            page = fetch(url, cache_dir / "groups" / f"{slug}.html",
                         force=force, ua=BROWSER_UA).read_text(errors="replace")
        except SystemExit as e:
            print(f"WARNING: psi {slug}: {e}")
            skips["fetch failed"] += 1
            continue
        tm = TITLE_RE.search(page)
        pm = SCHED_P_RE.search(page)
        if not tm or not pm:
            skips["no title/schedule block"] += 1
            print(f"psi: skip {slug} — page structure unexpected")
            continue
        name = re.sub(r"\s+", " ",
                      htmllib.unescape(TAG_RE.sub("", tm[1]))).strip()
        entries, segments = parse_schedule(pm[1])
        if not entries:
            skips["unparseable schedule"] += 1
            print(f"psi: skip {slug} — schedule not day+time: "
                  f"{' | '.join(segments)[:90]!r}")
            continue
        exact = (name.lower(), entries[0]["day"], entries[0]["time"])
        if exact in seen_exact:
            skips["duplicate"] += 1
            continue
        seen_exact.add(exact)
        records.append({
            "_state": "us", "_place_slug": "online", "_name": name,
            "program": "psi",
            "categories": ["mental-health", "peer-support", "family-support"],
            "schedule": entries,
            "format": "online",
            "url": url,
            "external_ids": Flow(psi=slug),
            "sources": [source_id],
            "verified": Flow(on=today(), method="scrape"),
        })

    print(f"psi: kept {len(records)} of {len(slugs)} groups; skips: {dict(skips)}")
    if len(records) < 25:
        raise SystemExit(f"psi: only {len(records)} groups — expected 30+; aborting")
    replace_records("meetings", source_id, records)


if __name__ == "__main__":
    main(sys.argv[1:])
