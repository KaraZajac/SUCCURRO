# Discovery engine — standing BMF-verify pipeline

*2026-07 · design · pilot batch: `pipeline/curated/discovered/2026-07-pilot.yaml` via `pipeline/discovered.py`*

Turns the BMF gap audit (`bmf-gap-audit-2026-07.md`) into records: pick nonprofits the IRS says
exist where SUCCURRO has nothing, verify each against its own live website, and emit only what
verification survives. The BMF is a candidate generator, never a source of record content.

## Candidate selection

- Unit of work: **(NTEE class group × audit-gap city)** — e.g. P81 × Philadelphia, {F40,F42,P43} × Phoenix.
- Pull from cached `sources/irs/eo*.csv` by `NTEE_CD` prefix + `CITY`/`STATE` exact match
  (the audit's class→category mapping is authority).
- Priority order = the audit's "where to hunt next": seniors and crisis first (worst coverage),
  then financial, then remaining classes; skip cities the audit flags as mailing artifacts
  (Oceanport NJ, AFB rows, Springfield VA).
- Pre-filter before any web work: drop candidates whose normalized name+state already exists in
  `data/orgs/` (including aliases). No other BMF field is trusted enough to filter on — foundation
  codes and residential-looking addresses are hints for ordering, not exclusion.

## Verification protocol

For each candidate, in order; any failure rejects:

1. **Find the org's own website** (web search on name + city). Aggregator/registry pages
   (ProPublica, Cause IQ, GuideStar) never count as the org's site.
2. **Confirm live + identity** — page loads, clearly this org (name/EIN/city consistent).
3. **Confirm current direct services** matching the category: a program page describing services
   delivered to the public now. Reject grantmakers, employee/benevolent funds, boosters,
   awareness-/events-only orgs, and category mismatches.
4. **Confirm geography** — still operating in-state; moved-away orgs are rejected, moved-within-metro
   noted and kept.
5. **Extract facts from the org's site only**: operating name (BMF legal name → `aliases` when it
   differs), website, address (city/state minimum), phone if published, one factual sentence of
   services. **DV policy: orgs providing domestic-violence services get no address at any
   precision beyond city hint — city/state land in `service_area`, never `address`.**

## Record shape

Batch YAML holds schema-shaped org records plus loader-consumed keys (`state`, `city` hint,
`checked`, `verified_on`). The loader (`pipeline/discovered.py`) adds:

- `sources: [discovered/<batch>]` — one per-batch source record (`data/sources/discovered/`),
  kind `org-website`, `url: null` + methodology notes (each org's `website` field is the page it
  was verified against — lgbtqseed pattern).
- `verified: {on: <run date>, method: scrape}` and `provisional: true` — human-in-the-loop web
  check, but single-pass and unconfirmed by the org, so provisional until a second source or a
  human re-check corroborates.
- `place` FK resolved from the address/city hint (so gap-audit coverage joins count these).
- `external_ids: {ein: ...}` kept from the BMF for future cross-source joins (ProPublica enrichment).
- `checked:` (what the run confirmed, on which pages) stays in the batch file as audit trail;
  it is **not emitted** — descriptions stay clean, provenance stays reviewable.

## Cadence, dedup, ownership

- **Monthly batch** per BMF refresh window: one YAML file `<YYYY-MM>-<theme>.yaml`, ~40-60 verified
  orgs ≈ a day of verification work. Re-running the loader is idempotent; the `discovered/` source
  prefix owns all batch records, so batches never clobber other pipelines.
- **Dedup twice**: at candidate pull (cheap, saves web work) and again in the loader (normalized
  name+state vs. non-batch orgs — skip, never overwrite). If a later dedicated source (e.g.
  Eldercare Locator) lands the same org, precedence rules retire the provisional record.
- Re-verification: batch records age under the standard 180-day org staleness gate; a stale batch
  is re-run (same file, new `run_on`), dead orgs deleted from the file.

## Failure taxonomy (per-candidate reject reasons, reported per run)

`dead-site` · `no-web-presence` · `social-only` (Facebook-only orgs — real but unverifiable to our
bar) · `wrong-services` (real org, NTEE ≠ what it does) · `grantmaker` (funds providers, isn't one)
· `internal-fund` (employee/member relief) · `moved` (left the state) · `defunct` (announced
closure/merger) · `unverifiable` (site up, current services unconfirmable).

## Honest limits

- **Survivorship of the webbed**: orgs without websites — disproportionately the small, volunteer-run,
  non-English ones serving the poorest places — are systematically excluded. This engine narrows the
  measured gap, not the real one; it complements, never replaces, dedicated directory sources.
- Single-scrape verification: a live site with a services page can still be a zombie (site outlives
  program). Hence `provisional: true` and the 180-day re-check.
- BMF city ≠ service city (mailing addresses); we verify operations in-metro, not at the BMF address.
- Yield is class-dependent: P60 pools are mostly paper orgs and grantmakers (expect <25% keep);
  P81/P43 pools keep 40-60%. Burn rate, not candidate count, is the planning number.
- One person-day per ~40 verified orgs does not scale to the 50k+ uncovered-org backlog; the engine
  is for gap cities where no directory source exists, and each batch should also scout whether a
  proper source (AAA rosters, DV coalitions) could replace hand-verification for its class.
