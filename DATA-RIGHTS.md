# Data rights

The one rule (family-wide): **publish facts and original curation, not third-party
content.** Raw source pages/feeds live only in gitignored `sources/`; what's committed
is factual records (names, addresses, schedules, phone numbers — facts are not
copyrightable) plus URL, archive URL, and retrieval date for every claim.

## Layers

| Layer | Contents | Provenance | Terms |
|---|---|---|---|
| `data/orgs`, `data/sites`, `data/meetings` | Curated factual records | Original curation over sources below | CC BY-NC 4.0 |
| `data/places` | Place registry | US Census Bureau gazetteer | Public domain (US federal) |
| `data/taxonomy`, `docs/`, `schemas/` | Original work | This project | CC BY-NC 4.0 / MIT (code) |
| `data/sources` | Provenance metadata (URLs, dates, hashes) | Original | CC BY-NC 4.0 |
| `sources/` (gitignored) | Raw downloads, scrape caches | Upstream | Upstream terms; never redistributed |

## Per-source terms

| Source | Terms | Handling |
|---|---|---|
| Census, SAMHSA, HRSA, HUD, USDA, VA (CC0), ACF (Head Start, RHY, FVPSA, LIHEAP), IRS EO BMF, EOIR | US federal public domain | Full use, attributed |
| BMLT (NA), TSML feeds (AA, Recovery Dharma, Refuge Recovery) | Open community feeds, no stated license; Meeting Guide spec is MIT | Facts extracted, feed cited per record; courtesy notification; honor any service-body takedown request |
| Al-Anon WSO locator dataset | Widget data URL, not an offered API; © Al-Anon HQ | Permission email before redistribution; facts-only |
| Mutual Aid Hub | **PDDL 1.0** (public-domain dedication) | Full use, attributed; snapshot early (fragile endpoint) |
| feedam.org HSDS | CC BY-SA / CC BY (inconsistent); relicensing of 211/AmpleHarvest slices questionable | Federal-derived slices usable; rest **not ingestable** — SA share-alike is incompatible with our BY-NC umbrella |
| Eldercare Locator (ACL) | **ODbL 1.0** per data.gov | Share-alike/attribution obligations if ingested — decide before use |
| NAMI, PFLAG, Feeding America, NNEDV, CenterLink, NDBN, MHA, Clubhouse, CCUSA, LSC, 988 roster | Org sites, ToS vary; facts-only | Facts-only re-expression, per-record citation + archive link; throttled, robots-respecting |
| ProPublica Nonprofit Explorer | Attribution + link required; no paywalling | Enrichment only, attributed |
| 211/United Way, findhelp.org | ToS restrict bulk use | **Not bulk-collected.** Manual gap-fill/verification only, cited as secondary |
| domesticshelters.org, OutCare, In The Rooms, Vivery/AccessFood, FoodPantries.org, NFCC, GriefShare, American Cancer Society | ToS prohibit scraping/reuse (verified) | **Not ingested.** Link-out only; Vivery/AmpleHarvest/IAN via partnership ask |
| Al-Anon WSO, Immigration Advocates Network | Asked 2026-07-19; no restrictive ToS exists (verified) | No reply by 2026-08-09 → facts-only ingestion, attributed, takedown honored |
| AmpleHarvest | ToS §3 requires prior written consent for redistribution (verified) | **Ingest only on an affirmative yes** |
| ThroughLine, NSPN | No public bulk; partnership-friendly orgs | Contact first — do not scrape |

## Umbrella license

Dataset (`data/`): **CC BY-NC 4.0**. Code (`pipeline/`, `site/`, `schemas/`): **MIT**.

## Safety and ethics posture

This dataset describes services for people in crisis. Accordingly:

- **Freshness over completeness.** Records failing staleness thresholds are flagged
  and, for safety-critical categories (crisis lines, shelters), suppressed from the
  site rather than shown stale.
- **DV shelter addresses:** confidential shelter locations are *never* published even
  if discoverable; only hotline/intake contact is recorded. The validator enforces
  `address`-omission for records tagged `dv-confidential`.
- **12-step anonymity:** meeting records carry venue and schedule facts only — never
  names of members or contacts beyond published intergroup phone numbers.
- **Takedown:** any listed org may request correction or removal; honored without
  argument. Contact in README.

## Citation

If you use this dataset, cite it (see `CITATION.cff`) and the upstream sources listed
in each record's `sources:` entries.
