# Prior-art survey: existing datasets and SUCCURRO's contribution

Research sweep 2026-07-19 (primary-source verified: live Overpass queries, ICPSR
study pages, federal portals). Question: does any existing dataset — especially
DOI-published — already cover what SUCCURRO builds?

**Verdict: no.** Nothing found is simultaneously (a) national, (b) point/city-
resolved, (c) multi-category across help-services domains, (d) openly licensed,
and (e) maintained. Every candidate fails at least two.

## NaNDA (National Neighborhood Data Archive, UMich/ICPSR)

Publishes **no point locations, names, or addresses** — only counts/densities per
census tract/ZCTA, derived from the proprietary NETS database (D&B via Walls &
Associates), which it cannot redistribute at record level.

- Social Services by Tract & ZCTA 1990–2021 — DOI 10.3886/E208207V3 — CC BY-NC 4.0
- Civic/Social/Religious Orgs 1990–2021 — DOI 10.3886/E207966V1 — CC BY-NC 4.0
- Health Care Services 1990–2022 — E209050

Role for SUCCURRO: validation/benchmark layer (tract-density cross-checks) and
NAICS 624/813 taxonomy reference. (SUCCURRO is also CC BY-NC by choice — the
license differentiator vs NaNDA is point-level records with per-record
provenance, not the license terms.)

## ICPSR / academic point-level attempts

- **N-SUMHSS** (SAMHDA): public-use files de-identified to state level — the
  address-bearing data is SAMHSA's locator (our source #13).
- **OEPS** (Opioid Environment Policy Scan, Zenodo 10.5281/zenodo.5842465):
  closest point-level prior art, opioid/health vertical only; repo has national
  geocoded CSVs but **no license file** — reuse terms murky.
- **Charitable Food Dataset** (DOI 10.34990/FK2/GHL06P): 3,777 pantries, 12
  states, 2019, CC0 — citation anchor + seed.
- **National food-pantry accessibility dataset** (Sci Reports 2026, OSF
  px9t8): 34,475 pantries, 2022 snapshot, **no data license**, Google-Maps-
  derived (ToS-encumbered), no operational attributes.
- **Geocoded LGBT community centers** (Martos et al. 2017, CC-BY): 306 centers,
  2015 fieldwork — only DOI'd national LGBTQ+-center points, a decade old.
- Closed/never-released: 48,581-pantry census (JNEB 2023), NSTARR recovery
  residences, NETS-based social-services panels. Pattern worth citing: the best
  national attempts were **license-blocked by their upstreams** — provenance
  discipline is itself the contribution.

## Federal landscape

**HIFLD Open was discontinued Aug 2025** (layers moved behind DHS DUA-gated
access; DataLumos/HIFLD Next hold frozen snapshots only). Live per-silo feeds:
SAMHSA, HRSA, VA (all already SUCCURRO sources), FEMA National Shelter System
(disaster shelters only). **HUD publishes no open shelter point dataset** (HIC/
PIT are bed-count aggregates) — a real gap SUCCURRO fills. No federal source
covers recovery meetings, peer support, food banks, LGBTQ+ centers, crisis-line
directories, or legal aid points.

## Open Referral / HSDS

No one has published a national aggregated US HSDS dataset, DOI or otherwise.
Pilots are regional and mostly dormant. HSDS is the format SUCCURRO should
**emit**, not a competitor — a national HSDS-conformant release with a DOI would
be a first.

## Closed incumbents (benchmarks only)

findhelp (970k+ program locations, display-only API terms); United Way 211 NDP
(~99% population reach, data-sharing agreements, reportedly CC BY-NC-SA at
best); Unite Us; Feeding America (publishes statistics, never the directory);
NRD.gov (search only). No peer-reviewed national audit of 211 coverage exists —
an evaluation gap the paper can note.

## OpenStreetMap

US coverage is thin (live Overpass, 2026-07-19): social_facility=food_bank
1,696 (~3% of network), shelter 862 (<15%), soup_kitchen 95; no legal-aid tag.
Completeness bias runs against low-income areas (Herfort 2023). **ODbL trap**
(per OSMF Collective Database Guideline): merging + deduplicating OSM records
makes the merged layer a derivative database that must be ODbL — foreclosing
CC-BY release. Safe uses: side-by-side collective layer, QA cross-checks.

## Gap table

| Category | Best existing open national source | Gap |
|---|---|---|
| SU/MH treatment | SAMHSA locator (point-level) | small — we add curation/provenance |
| Safety-net clinics | HRSA daily CSV | small — ingest, don't rebuild |
| VA services | VA Facilities API | small; community veteran orgs uncovered |
| Food banks/pantries | none current+licensed | **large** |
| Homeless shelters | none (HUD aggregates; FEMA disaster-only) | **large, worsened 2025** |
| Recovery meetings | **nothing, anywhere** | **total white space** |
| MH peer support | nothing national/open | **total white space** |
| LGBTQ+ centers | one CC-BY 2015 dataset | **large** |
| Crisis lines | no open directory (988 roster unpublished) | **white space** |
| Legal aid | LSC service areas, no office points | **large** |

## Claimable novelty (paper / Zenodo record)

1. First cross-category, national, point/city-resolved, openly licensed
   help-services dataset.
2. First national open dataset at all for recovery meetings, peer support,
   crisis-line directories, and current LGBTQ+ centers.
3. Per-record provenance + freshness stamps — no prior effort has them; the two
   best prior attempts died on provenance/licensing.
4. First national HSDS-format published dataset with a DOI, if we emit HSDS.
5. Cite NaNDA/OEPS as aggregate prior art; declare SAMHSA/HRSA/VA/FEMA as
   upstreams; benchmark coverage against findhelp/211 as closed baselines.

Confidence notes: high on NaNDA granularity/licenses, HIFLD timeline, OSM
counts, federal characteristics; medium on the 211 NDP license claim, OEPS
terms, and the negative "no national AA/NA dataset exists" (thoroughly searched;
negatives are never certain).
