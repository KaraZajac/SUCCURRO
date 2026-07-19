# Data rights

The one rule (family-wide): **publish facts and original curation, not third-party
content.** Raw source pages/feeds live only in gitignored `sources/`; what's committed
is factual records (names, addresses, schedules, phone numbers — facts are not
copyrightable) plus URL, archive URL, and retrieval date for every claim.

## Layers

| Layer | Contents | Provenance | Terms |
|---|---|---|---|
| `data/orgs`, `data/sites`, `data/meetings` | Curated factual records | Original curation over sources below | CC BY 4.0 |
| `data/places` | Place registry | US Census Bureau gazetteer | Public domain (US federal) |
| `data/taxonomy`, `docs/`, `schemas/` | Original work | This project | CC BY 4.0 / MIT (code) |
| `data/sources` | Provenance metadata (URLs, dates, hashes) | Original | CC BY 4.0 |
| `sources/` (gitignored) | Raw downloads, scrape caches | Upstream | Upstream terms; never redistributed |

## Per-source terms

| Source | Terms | Handling |
|---|---|---|
| Census, SAMHSA, HRSA, HUD, USDA, VA | US federal public domain | Full use, attributed |
| BMLT (NA), TSML feeds (AA), Al-Anon API | Open formats published for reuse | Facts extracted, feed cited per record; honor any intergroup takedown request |
| NAMI, Feeding America, CenterLink directory scrapes | Site ToS vary | Facts-only re-expression, per-record citation + archive link; throttled, robots-respecting collection |
| 211/United Way, findhelp.org | ToS restrict bulk use | **Not bulk-collected.** Manual gap-fill/verification only, cited as secondary |
| domesticshelters.org | ToS restricts reuse | Pending rights review; default is link-out, not ingestion |

## Umbrella license

Dataset (`data/`): **CC BY 4.0**. Code (`pipeline/`, `site/`, `schemas/`): **MIT**.

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
