# Source registry

Numbered registry of upstream sources, JUDGMENT-style. Status: **in-use** (pipeline
module exists), **planned** (identified, not yet built), **tested** (probed, notes
recorded), **rejected** (with reason). Rights notes summarize; `DATA-RIGHTS.md`
governs.

## Geo backbone

1. **Census Bureau Gazetteer Files** — status: **in-use** (`pipeline/places.py`).
   National places + county subdivisions, with GEOID, name, LSAD, coordinates.
   Public domain. https://www.census.gov/geographies/reference-files/time-series/geo/gazetteer-files.html

## Recovery / mutual aid

2. **AA Meeting Guide / TSML feeds** — status: **planned**. Most AA intergroups
   publish a Meeting Guide-compatible JSON feed (the 12-Step Meeting List WordPress
   plugin exports `?tsml-json` or `/wp-admin/admin-ajax.php?action=meetings`). Feed
   discovery per intergroup required; the Meeting Guide app's central aggregation is
   not public. Spec: https://github.com/code4recovery/spec — Code for Recovery also
   runs central tooling worth probing (sheets, central.aa feeds).
3. **NA BMLT root servers** — status: **planned**. Basic Meeting List Toolkit; public
   aggregator at https://aggregator.bmltenabled.org (all known root servers, JSON,
   semantic endpoints). Effectively the national NA meeting dataset.
4. **Al-Anon meeting search** — status: **planned**. al-anon.org meeting API (used by
   their mobile app); many areas also run TSML.
5. **SMART Recovery meeting finder** — status: **planned**. smartrecovery.org locator.
6. **SAMHSA FindTreatment.gov** — status: **planned**. Official substance-use +
   mental-health treatment facility dataset; bulk download available (Locator data).
   Public domain (federal).

## Mental health

7. **NAMI affiliate directory** — status: **planned**. State orgs + local affiliates;
   scrape of nami.org find-support pages; affiliates' own sites list support groups.
8. **988 / crisis center network** — status: **planned**. 988 Lifeline network centers;
   Vibrant publishes limited directory data.
9. **HRSA Find a Health Center** — status: **planned**. All FQHCs/community health
   centers; bulk CSV download at data.hrsa.gov. Public domain (federal).

## Housing / shelter

10. **HUD Continuum of Care + Housing Inventory Count** — status: **planned**. CoC
    contacts and shelter inventory; HUD Exchange downloads. Public domain (federal).
11. **HUD Find Shelter tool** — status: **tested→probe**. hud.gov find-shelter has a
    queryable backend; coverage of emergency shelters, food, health care.
12. **domesticshelters.org** — status: **planned, rights review required**. Largest DV
    shelter directory; ToS restricts bulk use — likely facts-only re-expression or
    link-out. Decide in DATA-RIGHTS before building.

## Food

13. **Feeding America network** — status: **planned**. ~200 member food banks
    (find-your-local-foodbank pages, zip→bank mapping); each bank's own agency/pantry
    locator (often Vivery/PantryNet platforms) is the hyper-local layer.
14. **Ample Harvest** — status: **planned**. ~4k registered pantries; probe API/rights.
15. **USDA SNAP retailer / summer meal sites** — status: **planned**. Federal, public
    domain; summer meal site files are per-year CSVs.

## Veterans

16. **VA Facilities API** — status: **planned**. api.va.gov/services/va_facilities —
    official, keyed, free; all VAMCs, CBOCs, Vet Centers with services/hours/geo.
    Public domain (federal).

## LGBTQ+

17. **CenterLink member directory** — status: **planned**. lgbtqcenters.org directory
    of ~300 community centers.
18. **Trevor Project / Trans Lifeline resource lists** — status: **planned**. National
    hotlines + curated resource links; mostly org-level records.

## Aggregators (secondary tier)

19. **211 / United Way** — status: **rejected for bulk, planned for gap-fill**. 211
    data is the most complete but is ToS-restricted (no bulk export); use only for
    manual verification/gap-fill, cite as secondary.
20. **findhelp.org (Aunt Bertha)** — status: **rejected**. Proprietary, ToS forbids
    scraping.
21. **Open Referral / HSDS publishers** — status: **planned**. Some regions publish
    open Human Services Data Specification datasets — free wins where they exist.
    Registry: https://openreferral.org

## Notes

- Federal datasets (1, 6, 9, 10, 15, 16) are public domain and bulk-friendly — build
  these first for national skeleton coverage.
- 12-step feeds (2–4) are open formats designed for reuse — the hyper-local meeting
  layer. Feed discovery (finding each intergroup's TSML endpoint) is itself a scraping
  task; maintain a curated feed registry in `pipeline/curated/feeds.yaml`.
- Directory scrapes (7, 13, 17) are brittle HTML — isolate per-site parsers, fail
  loud, archive every page to Wayback (AUSPEX `archive-sources` pattern).
