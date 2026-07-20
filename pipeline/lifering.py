"""LifeRing Secular Recovery meetings -> meeting records (recovery-meeting).

lifering.org's WordPress pages link out to meetings.lifering.org — the same
server-rendered Pathminder Meetings platform that SMART Recovery uses
(see pipeline/smart.py for the platform notes: no JSON API, /sitemap.xml
enumerates every meeting detail page, each page carries an AddEvent block +
address card + Pathcheck join link, plain urllib with the browser UA passes
Cloudflare). All crawling/parsing is shared with pipeline.smart; this module
just points it at the LifeRing instance (~160 meetings). One LifeRing
difference the shared parser handles: the AddEvent title carries a real
meeting name ("Global - West Coast Early Birds") rather than repeating the
home "City, State". Detail pages are cached one file per meeting under
sources/lifering/meetings/. Non-US meetings (LifeRing has a few
international ones) are dropped by the state filter.

Usage: python3 -m pipeline.lifering [--force]
"""
import re
import sys

from .emit import Places, write_source, replace_records
from .smart import crawl
from .util import BROWSER_UA, SOURCES, fetch

SITEMAP = "https://meetings.lifering.org/sitemap.xml"
BRAND = {
    "program": "lifering", "ext_key": "lifering", "prefix": "LifeRing",
    "url": "https://meetings.lifering.org/meetings/{}/",
    "generic_labels": {"how was your week meeting", ""},
}


def main(argv):
    force = "--force" in argv
    places = Places()
    cache_dir = SOURCES / "lifering"

    sitemap = fetch(SITEMAP, cache_dir / "sitemap.xml", force=force,
                    ua=BROWSER_UA).read_text()
    ids = sorted({int(m) for m in re.findall(
        r"<loc>https://meetings\.lifering\.org/meetings/(\d+)/</loc>", sitemap)})
    if len(ids) < 50:
        raise SystemExit(f"lifering: sitemap lists only {len(ids)} meetings — layout changed?")
    print(f"lifering: {len(ids)} meetings in sitemap")

    source_id = write_source(
        "lifering", "meeting-finder",
        kind="directory", publisher="LifeRing Secular Recovery",
        title="LifeRing Secular Recovery meeting finder",
        url="https://meetings.lifering.org/meetings/", tier="primary",
    )

    records = crawl(ids, cache_dir, places, source_id, force, brand=BRAND)
    if len(records) < 50:
        raise SystemExit(f"lifering: only {len(records)} US meetings — expected 50+; aborting")
    replace_records("meetings", source_id, records)


if __name__ == "__main__":
    main(sys.argv[1:])
