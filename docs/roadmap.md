# Roadmap

Dataset first, then the site. Phases are additive; `make verify` must stay green at
every step.

## Phase 0 — Skeleton (this commit)

Repo scaffold: docs, schema, taxonomy, validation gate, place registry pipeline,
governance files (DATA-RIGHTS, CITATION, hooks, Makefile).

## Phase 1 — Geo backbone

- `pipeline/places.py`: Census gazetteer → `data/places/<state>.yaml` (places +
  county subdivisions where operative). ~32k records nationally.
- ZIP→place crosswalk (Census ZCTA relationship files) for search-by-zip later.

## Phase 2 — Federal skeleton coverage (public domain, bulk downloads)

National org+site coverage from official datasets, one pipeline module each:
- SAMHSA FindTreatment locator data → treatment orgs/sites
- HRSA health centers → free/sliding-scale clinics
- VA Facilities API → veteran orgs/sites
- HUD CoC + shelter data → housing orgs/sites
- USDA summer meal sites → food sites

Deliverable: every US state has verifiable site-level records in ≥4 categories.

## Phase 3 — Mutual-aid meeting layer (open feeds)

- BMLT aggregator → NA meetings nationally (single source, biggest win)
- TSML feed registry (`pipeline/curated/feeds.yaml`) + harvester → AA meetings,
  intergroup by intergroup; budgeted harvest, JUDGMENT `lc-harvest` pattern
- Al-Anon API → Al-Anon/Alateen meetings
- SMART Recovery locator

Deliverable: meeting-level records with schedules, resolved to places.

## Phase 4 — Directory scrapes (brittle, per-site parsers)

- NAMI affiliates + support groups
- Feeding America banks → per-bank pantry locators (platform-specific parsers:
  Vivery, PantryNet, custom)
- CenterLink LGBTQ+ centers
- DV shelters (rights-cleared subset)

## Phase 5 — Reconciliation + enrichment

- Cross-source dedup via `external_ids` + normalized name/address join
- Geocoding gaps (Census geocoder API, free) + place assignment for every site/meeting
- Wayback archiving of all source URLs
- Staleness dashboard from validator soft findings

## Phase 6 — Astro site

- Family skeleton: Astro 7 static, `lib/data.js` loader, per-entity
  `getStaticPaths` pages
- Routes: `/state/<st>/`, `/<st>/<place>/` (the hyper-local landing page:
  everything in this town), `/org/...`, `/category/...`
- Search: Pagefind full-text + build-time JSON index for location+category
  faceting ("I'm in X and need Y"); per-state index shards to keep payloads small
- Scale note: meeting-level pages may push total page count past what full
  prerender handles comfortably — meetings render as sections of place pages, not
  individual pages, unless build times allow.

## Phase 7 — Operations

- CI: verify + site build (JUDGMENT ci.yml)
- Cron refresh workflows per source tier: monthly federal, weekly feeds,
  substantive-change-only commits with rebase-retry (JUDGMENT refresh.yml)
- Release bundles: JSONL export + SHA256SUMS + stats (AUSPEX export_release.py)
- Zenodo DOI once v1 coverage is real
