# Datasheet for SUCCURRO

Following the framework of Gebru et al., *Datasheets for Datasets* (2021).
Counts are from the tagged release; regenerate with
`python3 publish/export_release.py` (see `stats.json` in the bundle).

## Motivation

**Why was this dataset created?** Someone in crisis needs to know what help
exists in their own town, today. That information is scattered across federal
program databases, national nonprofit networks, individual fellowship feeds,
and thousands of local organizations' own websites — or locked inside
proprietary platforms. A prior-art survey (`docs/prior-art.md`) found no
existing dataset that is simultaneously national, resolved to point/city
level, multi-category, openly licensed, and maintained. Aggregate research
datasets (NaNDA) publish tract-level counts, not places you can go; the best
prior point-level attempts died on upstream licensing.

**Who created it and who funded it?** Kara Zajac, unfunded independent work.

## Composition

**What do the instances represent?** Three record types:

- **organizations** — entities that provide help (a NAMI affiliate, a food
  bank, a county veteran service office, a domestic violence coalition member)
- **sites** — physical locations where services are delivered (a pantry, a
  clinic, a shelter intake office, a VA facility)
- **meetings** — recurring gatherings (AA/NA/SMART/ACA meetings, grief
  support groups, peer support groups)

Supporting records: **places** (the Census-derived geo backbone of every US
city, town, CDP and New England town), **sources** (first-class provenance
records), and a **taxonomy** of service categories.

**How many instances?** At v1.0: 12,947 organizations, 136,038 sites, 77,714
meetings, across 32,307 places and 251 source records — roughly 260,000
records in 53 states and territories.

**What data does each instance consist of?** Name; service categories from a
controlled taxonomy; address, coordinates, and a foreign key to its place;
phone, email, website; hours or meeting schedule; eligibility, cost, languages
and free-text service labels where the source publishes them; upstream
identifiers; a `sources` list; and a `verified` stamp recording when and how
the record was last checked. Fields the source did not publish are omitted
rather than nulled.

**Is any information missing?** Yes, and unevenly. 88.3% of site and meeting
records carry coordinates and 90.3% a place foreign key; the remainder come
from sources that publish neither, and geocoding recovers only what the Census
geocoder can match. Hours, eligibility, languages, and cost are rich for some
sources (VA, SAMHSA, food bank locators) and absent for others. Coverage by
category is uneven — see *Limitations*.

**Is there a label or target?** No. This is a directory, not a supervised
learning dataset.

**Are there errors, noise, or redundancies?** Yes. Records inherit upstream
errors (misspelled cities, stale phone numbers, mis-plotted coordinates —
several sources were caught and repaired, e.g. a federal food-program layer
with scrambled geometry and truncated state names). Cross-source duplicates
are merged by normalized name and state for organizations and by address for
a known federal overlap, but co-located records offering different services
are deliberately kept separate, and some genuine duplicates certainly remain.

**Does it contain confidential or sensitive data?** By policy, no. Domestic
violence shelter locations are never published — only hotlines and intake
contacts, enforced in code. Recovery meeting records carry venue and schedule
facts only, never member or contact names, respecting fellowship anonymity
traditions. Personal contact details of individual staff or volunteers are
stripped during collection (organizational addresses only).

## Collection process

**How was the data acquired?** Programmatically, by ~60 source-specific
pipeline modules (`pipeline/`), from: US federal open data (SAMHSA, HRSA, VA,
HUD, USDA, ACF, IHS, DOJ, Census); open community feeds (the BMLT ecosystem
for NA, Meeting Guide/TSML feeds for AA, and eight other fellowships);
national nonprofit network directories (Feeding America member banks, NAMI,
PFLAG, CenterLink, The Arc, Community Action Agencies, and dozens more); and
state agency directories (DV coalitions, county veteran service offices, WIC
clinic layers).

**Was it sampled?** No sampling in the statistical sense — each module takes
everything its source publishes for the US. But the *set of sources* is a
convenience sample of what is publicly reachable and rights-clean, which is
the dominant selection effect in this dataset.

**Over what timeframe?** Collected July 2026; source records carry
`retrieved_on` dates and each record a `verified` date. A monthly refresh
workflow re-pulls every source.

**Were people involved?** No crowdworkers. Collection is automated; source
selection, rights review, and schema design are the author's.

**Ethical review?** No IRB (no human subjects). Ethics posture is documented
in `DATA-RIGHTS.md`: facts-only re-expression, per-record attribution,
takedowns honored without argument, and a published list of sources
deliberately *not* collected because their terms prohibit it.

## Preprocessing / cleaning / labeling

Raw pulls are cached (gitignored) and transformed into the canonical schema:
dates normalized to `YYYY-MM-DD` strings, phones to 10-digit dashed form,
scheme-less URLs prefixed, addresses parsed to structured fields, categories
mapped to the controlled taxonomy, and places resolved against the Census
registry (by name, then by nearest coordinate). Records failing schema
conformance or referential integrity block the build (`make verify`). Raw
source pages and feeds are never redistributed.

## Uses

**What has it been used for?** The succurro.org directory site.

**What else could it be used for?** Service-access research (coverage,
deserts, distance-to-care), referral tooling, civic applications, and
benchmarking against closed directories.

**Is there anything that should not be done with it?** Do not treat it as
authoritative for life-safety decisions without calling ahead — service hours
and locations change constantly. Do not use it to infer anything about the
individuals who use these services (it contains no service-user data). Do not
represent coverage gaps as evidence that services do not exist in a place; see
*Limitations*.

## Limitations

- **Coverage is categorically uneven.** An audit against the IRS Exempt
  Organizations file (`docs/research/bmf-gap-audit-2026-07.md`) found 95.5% of
  service-class registered nonprofits sit in a place the dataset covers, but
  only 68.5% sit in a place covered *for their own category*. Recovery, food,
  and youth services are dense; older-adult services and some crisis
  categories are thin.
- **Rights-driven omissions are systematic, not random.** Several of the
  largest directories (a pantry platform hosting ~75 food banks, the largest
  grief-support network, a national credit-counseling network, 211 data) are
  excluded because their terms prohibit collection. Their absence skews
  coverage in those categories.
- **Survivorship bias toward organizations with websites.** Discovery methods
  find providers that publish. A church pantry with no web presence is
  invisible here.
- **Freshness varies by source.** Federal datasets refresh on published
  schedules; scraped directories are as current as their publishers.
  Safety-critical categories are suppressed from the site when stale.
- **Meeting data is the most volatile.** Fellowship meetings move and close
  frequently; feed-published schedules are correct only as of the feed.

## Distribution

Distributed as a GitHub repository (canonical YAML) and as a citable release
bundle (JSONL + Open Referral HSDS 3.0 CSV tables + schema + statistics +
integrity manifest), archived on Zenodo with a DOI.

**License:** dataset CC BY-NC 4.0; code MIT. Upstream rights are layered per
source and documented in `DATA-RIGHTS.md`. Federal components are US
government works in the public domain.

## Maintenance

**Who maintains it?** Kara Zajac (kara@soulstone.org).

**How is it updated?** A monthly GitHub Actions workflow re-pulls every
source, re-runs reconciliation and enrichment, validates, and commits only
substantive changes. Each release is a frozen snapshot; the maintained version
is at succurro.org.

**How can others contribute or request removal?** Issues and pull requests at
github.com/KaraZajac/SUCCURRO, or email. Any listed organization may request
correction or removal; such requests are honored without argument.
