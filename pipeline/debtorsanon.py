"""Debtors Anonymous meetings -> meeting records (recovery-meeting).

Two server-rendered tables on debtorsanonymous.org:
- /meeting-search-f2f/?gt=&ct=&cn=USA&md= — all US in-person meetings in one
  table (day / "8:30 am Local time" / name + (DA|BDA #group) / city; the
  detail link's sn= param carries the state).
- /meeting-search-virtual/?mytz=Y&mytimezone=America/Chicago — worldwide
  virtual meetings ("12:00 am your time (7:00 am local)"), with an
  Originates column ("New York, US", "CA, US", plain "US", or foreign).
  The naive /meeting-search-virtual-first/ URL is just a JS timezone
  redirect stub; the mytimezone param is what makes the table render.
  Row times are meeting-local in the parenthesis; the row's Day column is
  in *your* (query) timezone, so the local weekday is recomputed from the
  your-time/local-time offset. "No specific time or day" (email/chat)
  rows are skipped — no schedule to record.

Each kept meeting's detail page (/meeting-search-detail/?mid=N) is also
crawled (cache sources/debtorsanon/detail/) for venue name + street + zip,
end time, open/closed, focus topics, language, and virtual access URLs. A
mid present in both tables becomes one hybrid record.

Usage: python3 -m pipeline.debtorsanon [--force]
"""
import html as htmllib
import re
import sys

from .bmlt import norm_state
from .emit import Places, replace_records, today, write_source
from .util import Flow, SOURCES, fetch, slugify

BASE = "https://debtorsanonymous.org"
F2F_URL = f"{BASE}/meeting-search-f2f/?gt=&ct=&cn=USA&md="
VIRTUAL_URL = f"{BASE}/meeting-search-virtual/?mytz=Y&mytimezone=America%2FChicago"
DETAIL_URL = f"{BASE}/meeting-search-detail/?mid={{}}"

DAYS = {"sunday": "sun", "monday": "mon", "tuesday": "tue", "wednesday": "wed",
        "thursday": "thu", "friday": "fri", "saturday": "sat"}
DAY_ORDER = ["sun", "mon", "tue", "wed", "thu", "fri", "sat"]
LANGS = {"english": "en", "spanish": "es", "french": "fr", "german": "de",
         "italian": "it", "portuguese": "pt", "russian": "ru", "hebrew": "he",
         "dutch": "nl", "farsi": "fa", "persian": "fa"}

TR_RE = re.compile(r"<tr.*?</tr>", re.S)
TD_RE = re.compile(r"<td[^>]*>(.*?)</td>", re.S)
MID_RE = re.compile(r"[?&]mid=(\d+)")
SN_RE = re.compile(r"[?&]sn=([A-Z]{2})")
GROUP_RE = re.compile(r"\((DA|BDA)\s*#(\d+)\)")
TIME_RE = re.compile(r"(\d{1,2}):(\d{2})\s*([ap])\.?m", re.I)
LOCAL_RE = re.compile(r"\(\s*(\d{1,2}):(\d{2})\s*([ap])m\s*local", re.I)
MULTI_RE = re.compile(r"Multiple Days:\s*([A-Za-z, ]+)")
TZ_LABEL_RE = re.compile(r"<i[^>]*>\s*([^<]*Time[^<]*?)\s*<")
# detail page bits (after normalizing </br> to <br>)
H2_RE = re.compile(r"<h2>(.*?)</h2>\s*<p>\s*(Open|Closed|Modified closed)?"
                   r"[^<]*meeting #\d+", re.S | re.I)
FOCUS_RE = re.compile(r"Meeting focus:</b>\s*([^<]+)")
LANG_LINE_RE = re.compile(r"Primary language:</b>\s*([^<]+)")
VENUE_RE = re.compile(r'Get Directions.*?</p>\s*<p class="plus">([^<]*)</p>'
                      r"\s*<p>(.*?)</p>", re.S)
DETAIL_TIME_RE = re.compile(
    r"<b>\s*[A-Za-z]+\s*<br>\s*(\d{1,2}):(\d{2})\s*([ap])m"
    r"(?:\s*to\s*(\d{1,2}):(\d{2})\s*([ap])m)?", re.I)
ACCESS_RE = re.compile(r"(?:Access|Subscription/Signup) info:.{0,200}?"
                       r"(https?://[^\s<\"']+)", re.S)
ADDR_LINE_RE = re.compile(r"^(.+?)\s+(\d{5})(?:-\d{4})?\s+US\.?$")


def split_city_state(citystate: str, by_state):
    """'Lakewood Colorado' / 'Salt Lake city Utah' / 'Barrington IL' ->
    (city, state) — the state is the longest recognizable trailing chunk."""
    tokens = citystate.split()
    for n in (3, 2, 1):
        if len(tokens) > n:
            st = norm_state(" ".join(tokens[-n:]), by_state)
            if st:
                return " ".join(tokens[:-n]), st
    return None, None


def clean(text: str) -> str:
    return re.sub(r"\s+", " ", htmllib.unescape(re.sub(r"<[^>]+>", " ", text))).strip()


def to_min(hh, mm, ap):
    return (int(hh) % 12 + (12 if ap.lower() == "p" else 0)) * 60 + int(mm)


def fmt_min(minutes):
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def parse_table(url, cache_name, force):
    html = fetch(url, SOURCES / "debtorsanon" / cache_name, force=force).read_text()
    tables = re.findall(r"<table.*?</table>", html, re.S)
    if not tables:
        raise SystemExit(f"debtorsanon: no table at {url}")
    return TR_RE.findall(tables[0])[1:]  # drop header row


def parse_f2f_rows(force):
    """-> {mid: row info} for the US in-person table."""
    out = {}
    for tr in parse_table(F2F_URL, "f2f.html", force):
        cells = TD_RE.findall(tr)
        if len(cells) < 5:
            continue
        mid_m, sn_m = MID_RE.search(tr), SN_RE.search(tr)
        day = DAYS.get(clean(cells[0]).lower())
        tm = TIME_RE.search(clean(cells[1]))
        if not (mid_m and day and tm):
            continue
        name_cell = clean(cells[2])
        gm = GROUP_RE.search(name_cell)
        out[mid_m.group(1)] = {
            "name": GROUP_RE.sub("", name_cell).strip(),
            "group": f"{gm.group(1)}-{gm.group(2)}" if gm else None,
            "bda": bool(gm and gm.group(1) == "BDA"),
            "days": [day],
            "time": fmt_min(to_min(tm[1], tm[2], tm[3])),
            "city": clean(cells[3]),
            "state": (sn_m.group(1).lower() if sn_m else None),
        }
    return out


def parse_virtual_rows(force, by_state):
    """-> ({mid: row info} for US virtual rows, skip counter)."""
    out, skips = {}, {}
    for tr in parse_table(VIRTUAL_URL, "virtual.html", force):
        cells = TD_RE.findall(tr)
        if len(cells) < 5:
            continue
        mid_m = MID_RE.search(tr)
        if not mid_m:
            continue
        mid = mid_m.group(1)
        origin = clean(cells[4])
        if not origin.endswith("US") or origin.endswith(("AUS",)):
            skips["non-US"] = skips.get("non-US", 0) + 1
            continue
        parts = [p.strip() for p in origin.split(",") if p.strip() and p.strip() != "US"]
        st = norm_state(parts[-1], by_state) if parts else None
        if not st:
            skips["US but no state"] = skips.get("US but no state", 0) + 1
            continue
        time_cell = clean(cells[1])
        name_cell = cells[2]
        lm = LOCAL_RE.search(time_cell)
        ym = TIME_RE.search(time_cell)  # first time = "your time"
        your_day = DAYS.get(clean(cells[0]).lower())
        if not (lm and ym and your_day):
            skips["no schedule"] = skips.get("no schedule", 0) + 1
            continue
        local_min, your_min = to_min(lm[1], lm[2], lm[3]), to_min(ym[1], ym[2], ym[3])
        # local weekday: shift the query-tz weekday by the tz offset carry
        offset = ((local_min - your_min + 720) % 1440) - 720
        carry = (DAY_ORDER.index(your_day) * 1440 + your_min + offset) // 1440
        local_day = DAY_ORDER[carry % 7]
        mm = MULTI_RE.search(clean(name_cell))
        days = ([DAYS[d.strip().lower()] for d in mm.group(1).split(",")
                 if d.strip().lower() in DAYS] if mm else [local_day])
        if mid in out:  # one row per weekday for multi-day meetings
            for d in days:
                if d not in out[mid]["days"]:
                    out[mid]["days"].append(d)
            continue
        name = clean(re.split(r"<br", name_cell)[0])
        gm = GROUP_RE.search(name)
        tz = TZ_LABEL_RE.search(name_cell)
        out[mid] = {
            "name": GROUP_RE.sub("", name).strip(),
            "group": f"{gm.group(1)}-{gm.group(2)}" if gm else None,
            "bda": bool(gm and gm.group(1) == "BDA"),
            "days": days,
            "time": fmt_min(local_min),
            "city": ", ".join(parts[:-1]) or None,
            "state": st,
            "tz": clean(tz.group(1)) if tz else None,
            "channel": clean(cells[3]).lower(),  # video / phone / email/chat
        }
    return out, skips


def parse_detail(mid, force, by_state):
    """Detail page enrichment; {} on fetch failure (loud)."""
    try:
        raw = fetch(DETAIL_URL.format(mid),
                    SOURCES / "debtorsanon" / "detail" / f"{mid}.html",
                    force=force).read_text()
    except SystemExit as e:
        print(f"WARNING: debtorsanon detail {mid}: {e}")
        return {}
    page = re.sub(r"</br>", "<br>", raw)
    info = {}
    hm = H2_RE.search(page)
    if hm:
        if clean(hm.group(1)):
            info["name"] = clean(hm.group(1))
        if hm.group(2):
            info["access"] = hm.group(2).lower().replace(" ", "-")
    fm = FOCUS_RE.search(page)
    if fm:
        info["focus"] = [clean(p) for p in fm.group(1).split(",") if clean(p)]
    lm = LANG_LINE_RE.search(page)
    if lm:
        info["lang"] = clean(lm.group(1)).lower()
    vm = VENUE_RE.search(page)
    if vm:
        if clean(vm.group(1)):
            info["venue_name"] = clean(vm.group(1))
        lines = [clean(l) for l in vm.group(2).split("<br>") if clean(l)]
        if lines:
            am = ADDR_LINE_RE.match(lines[-1])
            if am:
                city, st = split_city_state(am.group(1), by_state)
                if city and st:
                    info["city"], info["state"] = city, st
                    info["zip"] = am.group(2)
                    info["street"] = ", ".join(lines[:-1]) or None
    tm = DETAIL_TIME_RE.search(page)
    if tm:
        info["time"] = fmt_min(to_min(tm[1], tm[2], tm[3]))
        if tm.group(4):
            dur = (to_min(tm[4], tm[5], tm[6]) - to_min(tm[1], tm[2], tm[3])) % 1440
            if 0 < dur <= 480:
                info["duration"] = dur
    am = ACCESS_RE.search(page)
    if am:
        info["access_url"] = am.group(1).rstrip(".,")
    return info


def main(argv):
    force = "--force" in argv
    places = Places()

    source_id = write_source(
        "debtorsanon", "meeting-search",
        kind="directory", publisher="Debtors Anonymous",
        title="Debtors Anonymous meeting search (in-person + virtual)",
        url="https://debtorsanonymous.org/meeting-search-f2f/", tier="primary",
    )

    f2f = parse_f2f_rows(force)
    virtual, vskips = parse_virtual_rows(force, places.by_state)
    print(f"debtorsanon: {len(f2f)} US in-person rows, {len(virtual)} US virtual "
          f"meetings (virtual skips: {vskips})")

    records, seen_exact = [], set()
    skips: dict[str, int] = {}
    for mid in sorted(set(f2f) | set(virtual), key=int):
        base = f2f.get(mid) or virtual[mid]
        detail = parse_detail(mid, force, places.by_state)
        st = base["state"] or detail.get("state")
        if st not in places.by_state:
            skips["bad state"] = skips.get("bad state", 0) + 1
            continue
        in_person, online = mid in f2f, mid in virtual
        fmt = "hybrid" if in_person and online else \
              "in-person" if in_person else "online"

        time = detail.get("time") if in_person else None  # detail time is venue-local
        time = time or base["time"]
        schedule = []
        for day in base["days"]:
            entry = Flow(day=day, time=time)
            if detail.get("duration"):
                entry["duration_min"] = detail["duration"]
            schedule.append(entry)

        name = base["name"] or detail.get("name") or f"DA Meeting #{mid}"
        rec = {
            "_state": st, "_place_slug": "online", "_name": name,
            "program": "da",
            "categories": ["recovery-meeting"],
            "schedule": schedule,
            "format": fmt,
        }
        types = []
        if base.get("bda"):
            types.append("bda")
        if detail.get("access"):
            types.append(detail["access"])
        if online and (virtual.get(mid) or {}).get("channel") == "phone":
            types.append("phone")
        for label in detail.get("focus", []):
            token = slugify(label)
            if token and token not in types and len(types) < 8:
                types.append(token)
        if types:
            rec["types"] = types

        if in_person:
            city = detail.get("city") or base.get("city")
            geoid, place_slug = places.resolve(st, city or "")
            rec["_place_slug"] = place_slug
            if detail.get("venue_name"):
                rec["venue_name"] = detail["venue_name"]
            if city:
                venue = {"street": detail.get("street"), "city": city, "state": st}
                if detail.get("zip"):
                    venue["zip"] = detail["zip"]
                rec["venue"] = Flow({k: v for k, v in venue.items() if v})
            if geoid:
                rec["place"] = geoid

        if online:
            url = detail.get("access_url")
            if url:
                rec["conference_url"] = url
            tz = (virtual.get(mid) or {}).get("tz")
            if tz:
                rec["notes"] = tz

        code = LANGS.get(detail.get("lang", ""))
        if code:
            rec["languages"] = [code]

        ext = Flow(damid=mid)
        if base.get("group"):
            ext["da"] = base["group"]
        rec["external_ids"] = ext
        rec["sources"] = [source_id]
        rec["verified"] = Flow(on=today(), method="scrape")

        exact = (name.lower(), schedule[0]["day"], schedule[0]["time"],
                 st, rec["_place_slug"])
        if exact in seen_exact:
            continue
        seen_exact.add(exact)
        records.append(rec)

    by_fmt: dict[str, int] = {}
    for r in records:
        by_fmt[r["format"]] = by_fmt.get(r["format"], 0) + 1
    print(f"debtorsanon: kept {len(records)} ({by_fmt}); skips: {skips}")
    if len(records) < 100:
        raise SystemExit(f"debtorsanon: only {len(records)} meetings — expected 100+; aborting")
    replace_records("meetings", source_id, records)


if __name__ == "__main__":
    main(sys.argv[1:])
