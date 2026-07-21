"""Hand-curated national trans/LGBTQ+ support orgs -> org records.

Static seed (lifeline988.py pattern, but its own module and source id).
Every record was verified against the organization's live website on
2026-07-20 before inclusion:

- Point of Pride (pointofpride.org): live; surgery/HRT/electrolysis funds and
  free binder/shapewear programs confirmed on the site; no phone published.
- Transgender Law Center (transgenderlawcenter.org): live; phone 510-587-9696
  and prison/detention collect line 510-380-8229 from the contact page.
- SPARTA Pride (spartapride.org, formerly styled SPART*A): live; trans
  military community with private support groups; no phone published.
- LGBT National Youth Talkline 800-246-7743 and LGBT National Senior Hotline
  888-234-7243: numbers confirmed on lgbthotline.org; distinct from the main
  LGBT National Hotline already seeded by lifeline988.py.
- Trans Youth Equality Foundation (transyouthequality.org): live; phone
  207-478-4087 on the site.
- Gender Spectrum (genderspectrum.org): still operating, but its parent/
  grandparent/dad support groups are now hosted in partnership with PFLAG
  National — the description says so rather than implying its own groups.
- Q Chat Space: NOT included — qchatspace.org is a dead Azure placeholder
  ("404 Site Not Found") and CenterLink's site no longer mentions the
  program. Re-verify before ever re-adding.

One source record (kind org-website) covers the module; each org record's
own `website` field is the page it was verified against.

Usage: python3 -m pipeline.lgbtqseed
"""
import sys

from .emit import replace_records, today, write_source
from .util import Flow


def national(slug, name, cats, website, **fields):
    return {
        "_state": "us", "_place_slug": "", "_name": name,
        "id": f"us/{slug}",
        "categories": cats,
        **fields,
        "website": website,
        "service_area": Flow(kind="national"),
    }


ORGS = [
    national("point-of-pride", "Point of Pride",
             ["trans-services", "financial"],
             "https://www.pointofpride.org",
             description="Trans-led nonprofit providing direct financial aid "
                         "for gender-affirming care — Annual Trans Surgery "
                         "Fund, HRT Access Fund, Electrolysis Support Fund, "
                         "and Thrive Fund — plus free chest binders and "
                         "femme shapewear."),
    national("transgender-law-center", "Transgender Law Center",
             ["trans-services", "legal-aid"],
             "https://transgenderlawcenter.org",
             phone="510-587-9696",
             description="National trans-led legal organization: legal "
                         "information helpdesk, impact litigation, and a "
                         "prison mail program with a collect line for people "
                         "in prison and detention (510-380-8229)."),
    national("sparta-pride", "SPARTA Pride",
             ["trans-services", "veterans", "peer-support"],
             "https://spartapride.org",
             aliases=["SPART*A", "SPARTA"],
             description="Community of transgender service members, "
                         "veterans, their families, and allies — private "
                         "peer support groups, member grant programs, and "
                         "advocacy for open transgender military service."),
    national("lgbt-national-youth-talkline", "LGBT National Youth Talkline",
             ["lgbtq", "lgbtq-youth", "peer-support"],
             "https://lgbthotline.org/youth-talkline/",
             phone="800-246-7743",
             description="Free, confidential peer support, information, and "
                         "local resources for LGBTQ+ people ages 25 and "
                         "younger, from the LGBT National Help Center (not a "
                         "crisis line)."),
    national("lgbt-national-senior-hotline", "LGBT National Senior Hotline",
             ["lgbtq", "seniors", "peer-support"],
             "https://lgbthotline.org/senior-hotline/",
             phone="888-234-7243",
             description="Free, confidential peer support, information, and "
                         "local resources for LGBTQ+ older adults, from the "
                         "LGBT National Help Center (not a crisis line)."),
    national("trans-youth-equality-foundation", "Trans Youth Equality Foundation",
             ["trans-services", "lgbtq-youth", "family-support"],
             "https://www.transyouthequality.org",
             phone="207-478-4087",
             description="Supports transgender and gender-diverse youth and "
                         "their families through education, advocacy, youth "
                         "programs, and summer camps."),
    national("gender-spectrum", "Gender Spectrum",
             ["trans-services", "family-support"],
             "https://genderspectrum.org",
             description="Education and resources for gender-inclusive "
                         "environments for children and youth. Its parent, "
                         "grandparent, and dad support groups are now hosted "
                         "in partnership with PFLAG National (PFLAG "
                         "Connects)."),
]


def main(argv):
    source_id = write_source(
        "curated", "lgbtq-national-orgs",
        kind="org-website", publisher="SUCCURRO (hand-curated)",
        title="National trans/LGBTQ+ support organizations — curated seed",
        url=None,
        notes="Hand-curated set; each record's website field is the "
              "organization page it was verified against (see module "
              "docstring for per-org verification results).",
        tier="primary",
    )
    records = []
    for rec in ORGS:
        rec = dict(rec)
        rec["sources"] = [source_id]
        rec["verified"] = Flow(on=today(), method="scrape")
        records.append(rec)
    print(f"lgbtqseed: {len(records)} verified national orgs "
          "(Q Chat Space skipped — defunct)")
    replace_records("orgs", source_id, records)


if __name__ == "__main__":
    main(sys.argv[1:])
