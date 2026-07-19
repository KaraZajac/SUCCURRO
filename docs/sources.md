# Source registry

Numbered registry of upstream sources, JUDGMENT-style. Status: **in-use** (pipeline
module exists), **candidate** (endpoint verified, ready to build), **planned**
(identified, not yet probed), **probe** (needs technical/rights investigation),
**rejected** (with reason). Rights notes summarize; `DATA-RIGHTS.md` governs.

Endpoint details and record counts marked *verified* were live-tested 2026-07-19.

## Geo backbone

1. **Census Bureau Gazetteer Files** — **in-use** (`pipeline/places.py`). National
   places + county subdivisions with GEOID, LSAD, coordinates. Note: `<year>_Gazetteer/`
   dirs (singular); 2025 files are pipe-delimited. Public domain.
   https://www2.census.gov/geo/docs/maps-data/data/gazetteer/
2. **Census ZCTA relationship files + geocoder API** — **planned**. ZIP→place
   crosswalk for search-by-zip; free batch geocoder for address gaps. Public domain.

## Recovery meetings (mutual aid)

3. **NA — BMLT aggregator** — **candidate** (top priority). *Verified:*
   `https://aggregator.bmltenabled.org/main_server/client_interface/json/` (semantic
   interface), 44 root servers / 60,282 meetings worldwide, **~23,594 US meetings**
   across 26 US root servers; `/main_server/api/v1/rootservers` lists them with
   daily `lastSuccessfulImport`. Bulk strategy: hit each US root server directly
   (bare `GetSearchResults` returns the full dump on non-aggregator servers) or
   iterate the 1,601 service bodies. Open JSON, no key, no stated restrictions.
4. **AA — TSML feeds (12 Step Meeting List)** — **candidate**. Per-intergroup
   WordPress feeds: `https://<site>/wp-admin/admin-ajax.php?action=meetings` (or
   cached `/wp-content/tsml-cache-<hash>.json`); discoverable via
   `<link rel="alternate" type="application/json" title="Meetings Feed">`. Hundreds
   of intergroups; requires our own feed registry (`pipeline/curated/feeds.yaml`).
   Normalization target: Meeting Guide spec (MIT), github.com/code4recovery/spec.
   The AAWS Meeting Guide aggregate (~150k weekly meetings, 400–500 feeds) is
   internal — **not publicly available**.
5. **AA — OIAA online meetings** — **probe**. *Verified endpoint:*
   `https://central-query.apps.code4recovery.org/api/v1/meetings` (rich JSON) but
   responses window at ~51 records; pagination unresolved — ask in Code for
   Recovery's public Slack.
6. **Al-Anon/Alateen — WSO locator dataset** — **candidate (rights caveat)**.
   *Verified:* single 12.8 MB JSONP file behind their Store Locator Widgets embed,
   `https://cdn.storelocatorwidgets.com/json/cba0758378166b88cf39e82d3f2d02af` —
   **14,472 US/CA meetings** with lat/lng, language, format. One GET. Not an
   offered API — email WSO (afgmobile@al-anon.org) before redistribution.
7. **Recovery Dharma** — **candidate**. *Verified TSML feed:* 935 meetings at
   `https://recoverydharma.org/wp-admin/admin-ajax.php?action=meetings`.
8. **Refuge Recovery** — **candidate**. *Verified TSML feed:* 234 meetings at
   `https://refugerecoverymeetings.org/wp-admin/admin-ajax.php?action=meetings`.
9. **SMART Recovery** — **probe**. meetings.smartrecovery.org is behind an
   aggressive Cloudflare JS challenge; headless browser or partnership request.
10. **LifeRing** — **probe**. No machine feed; ~100–200 meetings; scrape or email.
11. **Celebrate Recovery** — **probe (low)**. Scrape-hostile custom locator; legacy
    Joomla locator has an expired TLS cert. Large network, fragile infra.
12. **In The Rooms** — **rejected**: auth-gated, ToS prohibits scraping, online-only.

## Treatment & health facilities (federal, public domain)

13. **SAMHSA FindTreatment.gov** — **candidate** (top priority). *Verified, no key:*
    `https://findtreatment.gov/locator/exportsAsJson/v2?...&pageSize=2000&page=N`
    returns full facility JSON (name, address, phone, lat/lng, services); ~30–40k
    SA+MH treatment facilities; updated weekly. Developer guide v1.11 (May 2026):
    https://findtreatment.gov/assets/FindTreatment-Developer-Guide.pdf
14. **HRSA Data Warehouse** — **candidate** (top priority). data.hrsa.gov/data/download:
    **16,200+ health-center service sites** (FQHCs) with addresses/geo, updated
    daily; plus Ryan White HIV care orgs (annual) and shortage-area files. Public
    domain.

## Mental health & crisis

15. **NAMI** — **candidate**. *Verified open REST API:*
    `https://www.nami.org/wp-json/wp/v2/affiliate?per_page=100&page=N` →
    **801 affiliates** (X-WP-Total), with per-state canonical pages. Support-group
    schedules live on individual affiliate sites (later layer). Also: **NAMI
    National Warmline Directory PDF** (quarterly, dated editions) — cleaner warmline
    source than warmline.org.
16. **988 Lifeline network centers** — **candidate**. ~200+ member crisis centers
    listed at 988lifeline.org (crisis-centers-by-state page); Cloudflare-protected,
    browser scrape; low churn, quarterly refresh. Plus static national records:
    988 call/text/chat + Veterans/Spanish/LGBTQ+-youth subnetworks, Crisis Text
    Line (HOME→741741), NAMI HelpLine.
17. **DBSA support groups** — **probe**. Server-rendered finder, no API; ~150
    chapters / ~600 groups; HTML scrape of state-filtered results.
18. **Mental Health America affiliates** — **planned**. *Verified sitemap:*
    `https://mhanational.org/affiliates-sitemap.xml` → 133 affiliate pages. Trivial
    scrape, low churn.
19. **Clubhouse International directory** — **planned**. ~300+ clubhouses, paginated
    server-rendered directory; small, stable.
20. **warmline.org** — **probe (secondary)**. Vercel bot-blocked (429s); use as
    cross-check against the NAMI warmline PDF.
21. **SPRC state pages** — **planned (low)**. State suicide-prevention contacts;
    enrichment only. **IASP** crisis-centre list — **rejected**: duplicative of 988.
22. **Find A Helpline (ThroughLine)** — **probe**. Real REST API
    (developer.throughlinecare.com), best helpline taxonomy anywhere, but a
    commercial product — license conversation required; do not scrape.

## Housing & shelter

23. **HUD Resource Locator ArcGIS backend** — **candidate** (top priority).
    *Verified keyless:* `https://egis.hud.gov/arcgis/rest/services/hrl/HudResourceLocator/MapServer`
    — layer 8: **384 CoC records** (contacts + service-area polygons, joinable to
    our places); layer 1: **3,483 Public Housing Authorities** with addresses.
    Bulk alternative: hudgis-hud.opendata.arcgis.com. Public domain.
24. **HUD Housing Inventory Count (HIC/PIT)** — **candidate (QA role only)**.
    Annual bed/unit counts by CoC — aggregates, not addresses; use to verify
    coverage. huduser.gov AHAR datasets. Public domain.
25. **HUD Find Shelter tool** — **rejected**: verified to be a client-side Google
    Places proxy now — there is no HUD-curated shelter dataset behind it.
26. **ACF FYSB RHY grantee lists** — **planned**. Runaway/homeless-youth program
    grantees (Basic Center, Transitional Living, Street Outreach) on per-state pages
    `acf.gov/fysb/grants/<state>-rhy`; several hundred orgs; best national
    youth-shelter list. Public domain.
27. **National Safe Place** — **probe**. ~140 licensed youth agencies (worth a
    facts-only scrape); thousands of designated sites behind an SMS locator —
    partnership ask to NSPN for site-level.
28. **shelterlistings.org / homelessshelterdirectory.org** — **rejected**:
    unverifiable provenance (themselves scraped), no reuse rights. Manual gap-fill
    with link-out at most.

## Domestic violence & sexual assault

Policy reminder (DATA-RIGHTS): confidential shelter locations are never published —
org/hotline/intake contacts only.

29. **NNEDV state coalition list** — **candidate**. 56 state/territory coalitions,
    single-page, org-level, policy-safe. Facts-only re-expression.
30. **ACF FVPSA grantees** — **planned**. 56 state administrators + ~250 tribal
    grantees (public domain); local subgrantee lists live with states, not ACF.
31. **domesticshelters.org** — **rejected**: ToS verified — prohibits scraping and
    content collection. Link-out only.
32. **RAINN local providers** — **probe + rights inquiry**. *Verified:* React SPA
    with internal JSON API at `https://centers.rainn.org/api`; 1,100+ providers.
    RAINN licenses the DB to partners — ask before use. Org/hotline fields only.
33. **VictimConnect** — **probe**. National hotline record now; Resource Map
    backend + rights later.

## Food & basic needs

34. **USDA SNAP Retailer Location Data** — **candidate**. *Verified:* **253,894
    retailers** (name, address, lat/lng, store type), ArcGIS FeatureServer
    `services1.arcgis.com/RLQu0rK7h4kbsBq5/.../snap_retailer_location_data/FeatureServer/0`
    + CSV bulk export; updated biweekly. Public domain. (Where to *use* benefits —
    also a strong geocoding anchor.)
35. **USDA Summer Meals Site Finder** — **candidate**. *Verified:* **58,269 sites**
    in the 2026 per-year FeatureServer on the same FNS ArcGIS org; weekly updates
    in season; pipeline must discover per-year layers. Public domain. (Note: USDA
    FNS renamed FNA June 2026; fns.usda.gov and fna.usda.gov both resolve.)
36. **USDA FDPIR/CSFP administering agencies** — **planned**. 162 commodity-food
    agencies (tribal food distribution, elderly food boxes), same ArcGIS org.
37. **WIC clinics** — **probe**. No national bulk dataset exists. Paths: state WIC
    agency ArcGIS layers (feed-registry pattern), FNS program-contacts page for the
    ~90 state/tribal agencies, signupwic.com is scrape-hostile.
38. **Feeding America member directory** — **candidate**. *Verified undocumented
    JSON API:* `https://www.feedingamerica.org/ws-api/GetAllOrganizations?...` →
    **198 food banks** with HQ, geo, contact, and counties-served FIPS lists. One
    request. Facts-only re-expression, note in DATA-RIGHTS.
39. **Pantry level via bank locator platforms (Vivery/AccessFood)** — **rejected
    for scraping** (ToS prohibits); **probe for partnership** (211 Metro Chicago
    precedent). Link2Feed: **rejected** — intake software, not a directory.
    Per-bank locators are heterogeneous — curated registry + isolated parsers if
    pursued.
40. **feedam.org HSDS 3.0 feed** — **probe → strong candidate (rights review)**.
    *Verified:* open Open Referral HSDS API (`https://feedam.org/hsds/v3/`,
    datapackage + CSV, 1,000/page) claiming **566,744 food-assistance locations /
    215,182 orgs** aggregated from USDA, HRSA, state WIC, 211 networks,
    AmpleHarvest, OSM. License inconsistently stated (CC BY-SA vs CC BY) and their
    right to relicense 211/AmpleHarvest slices is questionable; single-maintainer
    Cloudflare-worker infra. Use federal-derived slices freely; treat rest as
    secondary pending review; contact info@feedam.org. **Archive snapshots early.**
41. **AmpleHarvest** — **probe (contact first, do not scrape)**. 8,543 opt-in
    registered pantries; no API; their data already flows into feedam.org.
42. **Little Free Pantry map** — **candidate**. *Verified:* entire dataset embedded
    in-page (**4,886 pantries** as a JS array) at mapping.littlefreepantry.org.
    Take pantry facts only, drop submitter personal fields; courtesy email.
43. **Mutual Aid Hub** — **candidate (staleness caveat)**. *Verified publicly
    readable Firestore:* project `townhallproject-86312`, collections
    `mutual_aid_networks` (**900 docs**) and `food_resources` (233). **PDDL 1.0
    (public domain dedication)** — best license of any nonprofit source. Largely
    COVID-era; verify liveness; **snapshot early** (rules could close).
44. **National Diaper Bank Network** — **candidate**. *Verified:* member directory
    is a Google My Maps embed; KML export returns **250 member banks** in one
    request. Monthly re-pull.
45. **FoodPantries.org / FoodFinder.us** — **rejected**: ad-supported directories,
    all-rights-reserved, unclear provenance, nothing unique vs. better-rights
    sources.

## Veterans

46. **VA Facilities API (Lighthouse)** — **candidate** (top priority). *Verified:*
    `https://api.va.gov/services/va_facilities/v1` with `/facilities/all` bulk
    CSV/GeoJSON export; ~2,500–3,000 facilities (VAMCs, clinics, **Vet Centers**,
    VBA offices, cemeteries) with services, hours, geo. **CC0/public domain** (per
    data.gov). Free sandbox key, short application; production needs a demo call.
47. **National Resource Directory (nrd.gov)** — **probe**. ~16,000 vetted veteran
    resources; no export; sequential-ID detail pages look enumerable; federal =
    public domain; heavy filtering needed (many are link-level, not site-level).
48. **CVSO rosters (county veteran service officers)** — **probe, per-state**.
    No national roster (NACVSO is members-only); ~35+ state DVA sites publish
    county tables; seed from NASDVA's state links (nasdva.us/resources).
49. **VSO post locators (American Legion ~12.5k, VFW ~6k, DAV)** — **probe**.
    Personify/JSON XHR backends likely; ToS review before scraping. Skip
    third-party aggregators. Team RWB — low-priority; WWP — rejected (program
    offices, not services).

## Older adults

50. **Eldercare Locator (ACL)** — **probe**. 617 Area Agencies on Aging + 270+
    Title VI Native aging programs; no bulk export; **ODbL-licensed** per data.gov
    (notable — not PD). Probe the search backend or request the dataset from ACL.
51. **AGID/ACL State Profiles** — **planned**. State profile pages render SUA/AAA/
    Tribal directories with addresses — clean extraction route to the same
    universe. Public domain.

## LGBTQ+

52. **PFLAG chapters** — **candidate**. *Verified:* all **345 chapters** embedded
    as inline JSON (`chapter_data`) in pflag.org/findachapter — name, address,
    phone, email, lat/lng, website in one GET. Best effort/quality ratio in the
    domain. (Sample saved in scratchpad.)
53. **CenterLink LGBTQ+ centers** — **probe**. ~270 US centers; directory moved to
    a JS-rendered WebLink/MemberClicks SPA — one headless session to capture the
    XHR, likely clean JSON after.
54. **National LGBTQ+ hotlines** — **candidate (static seed)**. Trevor Project,
    Trans Lifeline, LGBT National Help Center lines (~8 records, hand-curated).
55. **LGBT Near Me** — **probe (partnership)**. Claims 22,000+ resources; ZIP-radius
    UI only; open public submissions (quality risk); ask for export.
56. **OutCare Health** — **rejected**: ToS explicitly prohibits scraping with
    liquidated damages. **GLMA directory** — **rejected (soft)**: unvetted
    individual providers, wrong granularity.

## Youth & family

57. **Head Start locations (ACF)** — **candidate** (top priority). *Verified ArcGIS
    FeatureServer:* **20,975 service locations** with full address, geo, funded
    slots, phones —
    `services2.arcgis.com/ZQ4jTQn6k7VPXEwO/.../ACF_Head_Start_Locations/FeatureServer/0`.
    Public domain.
58. **Boys & Girls Clubs (~4,700) / YMCA (~2,600)** — **probe**. Both need headless
    XHR capture of their map locators.
59. **Big Brothers Big Sisters** — **probe**. Legacy ASP.NET ZIP lookup (~230
    agencies); coarse ZIP sweep.
60. **Childcare.gov** — **planned (crosswalk)**. No national provider dataset;
    gateway to ~56 state search systems (per-state modules someday). Child Care
    Aware's 500k-program dataset is proprietary — **rejected**. CCR&R agency list
    (~400 referral agencies) — **probe**.

## Legal aid

61. **LSC grantees** — **candidate**. **129 programs** covering all states, with
    service areas, on lsc.gov; small scrape; ask datateam@lsc.gov for a bulk
    extract. Authoritative for civil legal aid.
62. **EOIR pro bono providers (immigration)** — **candidate**. Quarterly PDF
    (justice.gov/eoir), providers per immigration court with addresses; public
    domain; July 2026 edition current.
63. **Immigration Advocates Network directory** — **probe + rights inquiry (do not
    scrape first)**. 900+ nonprofit immigration legal providers, best-in-class;
    they already syndicate to partners — ask directory@immigrationadvocates.org.
64. **LawHelp.org portals** — **planned (gap-fill)**. ~20 statewide portals,
    heterogeneous. **ABA Free Legal Answers** — planned, low (state-level virtual
    clinic records).

## Utility & financial assistance

65. **LIHEAP Clearinghouse office directory** — **candidate**. *Verified enumerable
    DB:* `https://liheapch.acf.gov/db/states.php?State=<n>&County=<n>` — local
    intake offices per county nationwide. Public domain. (Skip liheap.org — private
    lookalike.)
66. **Community Action Agencies** — **planned**. ~1,000 CAAs;
    communityactionpartnership.com WP locator (probe ajax) + ACF association
    contacts page (PD).
67. **Salvation Army / St. Vincent de Paul / Catholic Charities** — **probe /
    planned**. SA: GDOS location-finder XHR probe (thousands of category-tagged
    sites). SVdP: ~4,400 conferences, probe locator. CCUSA: **169 agencies**,
    trivial scrape now; per-agency program sites are a later hyper-local layer.

## Cross-cutting mega-datasets

68. **IRS Exempt Organizations BMF** — **candidate (discovery seed, not
    directory)**. ~**1.98M nonprofits** with EIN, address, **NTEE codes** (E
    health, F mental health, K food, L housing, P human services, W30 veterans);
    monthly CSVs at irs.gov/pub/irs-soi/ (`eo1-4.csv`, per-state `eo_<st>.csv`).
    Caveats: mailing addresses not service sites, includes shells/defunct orgs.
    Use to seed per-city discovery and cross-validate — never publish directly.
    Public domain.
69. **ProPublica Nonprofit Explorer API** — **planned (enrichment)**. Keyless v2
    API (search by NTEE/state, org detail with 990 financials). Terms: attribution
    + link, no paywalling. Use to filter dead orgs from BMF seeds.
70. **Open Referral / HSDS publishers** — **planned (standing probe)**. HSDS 3.0
    is our interchange candidate; live US publishers are rare (feedam.org #40 is
    the big one; state 211 platforms are access-controlled). Collect regional
    feeds as found.
71. **data.gov / state portals** — **probe (per-region gap-fill)**. ~747 "social
    services" hits, mostly statistics; occasional city/county provider directories
    (LA FamilySource, NYC youth services). Opportunistic, not a national module.

## Aggregators (rejected for bulk)

72. **211 / United Way** — **rejected for bulk, manual gap-fill only** (ToS; no
    bulk export). Cite as secondary where used.
73. **findhelp.org (Aunt Bertha)** — **rejected**: proprietary, ToS forbids
    scraping.

## Build order (informed by verification)

Tier 1 — verified machine-readable bulk, license-clean or low-risk:
FindTreatment (13), HRSA (14), VA Facilities (46), Head Start (57), HUD ArcGIS
(23), SNAP retailers (34), Summer Meals (35), BMLT/NA (3), NAMI affiliates (15),
PFLAG (52), Feeding America banks (38), NDBN (44), Mutual Aid Hub (43 — snapshot
now), Little Free Pantry (42), LIHEAP (65), Al-Anon (6 — with permission email).

Tier 2 — small scrapes: NNEDV (29), LSC (61), EOIR (62), MHA (18), Clubhouse (19),
CCUSA (67), 988 centers (16), Catholic Charities.

Tier 3 — TSML feed registry buildout for AA (4), then headless probes (CenterLink,
BGCA/YMCA, SMART, RAINN, Salvation Army) and partnership asks (AmpleHarvest,
Vivery, IAN, ThroughLine, NSPN).

Archive-early (fragile endpoints): Mutual Aid Hub Firestore, feedam.org worker
API, Feeding America ws-api, NDBN KML, Al-Anon storelocator JSON.
