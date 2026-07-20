# Source registry

Numbered registry of upstream sources, JUDGMENT-style. Status: **in-use** (pipeline
module exists; count = records on disk citing the source), **candidate** (endpoint
verified, ready to build), **planned** (identified, not yet probed), **probe**
(needs technical/rights investigation), **held** (blocked on a permission reply or
a policy/license decision), **rejected** (with reason). Rights notes summarize;
`DATA-RIGHTS.md` governs.

Numbers are stable identifiers (cross-referenced from `docs/outreach.md` and
`pipeline/curated/feeds.yaml`); new sources get fresh numbers within their topical
section, so document order is not strictly numeric. Registry entries that fan out
into per-feed / per-layer / per-coalition source records (#4, #37, #87) explain why
55 in-use entries correspond to **117 source records** under `data/sources/`.
Counts for in-use entries are from the 2026-07-20 build (`data/meta.yaml`:
109,770 sites / 69,627 meetings / 7,133 orgs); endpoint details and counts marked
*verified* on candidate/probe entries were live-tested 2026-07-19/20.

## Geo backbone

1. **Census Bureau Gazetteer Files** — **in-use** (`pipeline/places.py`, 32,307
   places). National places + county subdivisions with GEOID, LSAD, coordinates.
   Note: `<year>_Gazetteer/` dirs (singular); 2025 files are pipe-delimited.
   `pipeline/geometry.py` adds state outlines from the cartographic boundary
   shapefiles. Public domain.
   https://www2.census.gov/geo/docs/maps-data/data/gazetteer/
2. **Census ZCTA relationship files + geocoder API** — **in-use**
   (`pipeline/zips.py` → `data/crosswalk/zips.yaml`, ~33k ZCTA centroids for
   search-by-zip; `pipeline/enrich.py` batches address gaps to the free Census
   geocoder, cached in `sources/geocode/`). Public domain.

## Recovery meetings (mutual aid)

3. **NA — BMLT aggregator** — **in-use** (`pipeline/bmlt.py`, 22,397 meetings).
   The aggregator's `/api/v1/rootservers` lists every root server (44 as of
   2026-07); each server's own `client_interface/json/?switcher=GetSearchResults`
   returns its full dump (the aggregator itself returns `[]` for a bare query, so
   we pull per-server). Non-US servers fetched but state-filtered; a failing
   server is skipped, not fatal. Open JSON, no key, no stated restrictions.
4. **AA — TSML feeds (12 Step Meeting List)** — **in-use** (`pipeline/tsml.py` +
   `pipeline/curated/feeds.yaml`, 45 feeds, 41,216 meetings; 40,213 AA-only, the
   rest are Recovery Dharma/Refuge Recovery, #7–8). One source record per feed
   (`aa/<feed-id>`); cross-feed dedup on (name, day, time, city). Normalization
   target: Meeting Guide spec (MIT), github.com/code4recovery/spec. Seventeen
   more intergroups run TSML with *restricted* feeds — sharing-key request
   emails drafted (`docs/outreach.md` batch 2, not yet sent). The AAWS Meeting
   Guide aggregate itself remains **not publicly available**.
5. **AA — OIAA online meetings** — **probe**. *Verified endpoint:*
   `https://central-query.apps.code4recovery.org/api/v1/meetings` (rich JSON) but
   responses window at ~51 records; pagination unresolved — ask in Code for
   Recovery's public Slack.
6. **Al-Anon/Alateen — WSO locator dataset** — **held (permission clock)**.
   *Verified:* single 12.8 MB JSONP file behind their Store Locator Widgets embed
   — **14,472 US/CA meetings** with lat/lng, language, format. One GET. Not an
   offered API. Permission email sent 2026-07-19; no ToS exists on al-anon.org
   (verified 2026-07-20), so per the fallback policy (`docs/outreach.md`) no
   reply by **2026-08-09** → facts-only ingestion, attributed, takedown honored.
7. **Recovery Dharma** — **in-use** (via `pipeline/tsml.py`, feed
   `aa/recoverydharma`, 843 meetings).
8. **Refuge Recovery** — **in-use** (via `pipeline/tsml.py`, feed
   `aa/refugerecovery`, 160 meetings).
9. **SMART Recovery** — **in-use** (`pipeline/smart.py`, 1,234 meetings).
   The Cloudflare challenge is passive as of 2026-07 — plain urllib with a
   browser UA passes. No JSON API: `/sitemap.xml` enumerates ~1,250 meeting
   detail pages (Pathminder Meetings platform), each with an AddEvent block
   (local start/end, IANA tz, RRULE BYDAY), address card, and join link.
   Builds entirely from cache; re-capture with Playwright if the challenge
   turns active again.
10. **LifeRing** — **in-use** (`pipeline/lifering.py`, 157 meetings). Same
    Pathminder platform as SMART; crawling/parsing shared with `pipeline/smart.py`,
    pointed at meetings.lifering.org.
11. **Celebrate Recovery** — **held (blocked)**. Locator is now behind
    **reCAPTCHA** (previously: expired-TLS legacy Joomla). Large network,
    fragile, scrape-hostile infra — permission-first if ever pursued.
12. **In The Rooms** — **rejected**: auth-gated, ToS prohibits scraping, online-only.

*Added 2026-07 (round-2 fellowship sweep):*

74. **Gamblers Anonymous** — **in-use** (`pipeline/gamblersanon.py`, 1,425
    meetings). The WP Event Manager detail pages (2,996 in sitemaps, worldwide)
    publish *no* times — only the site's server-side finder renders them:
    `/usa-meetings/` (per-state, term=147) + `/virtual-meetings/` (term=133),
    5 cards/page, crawled and cached per page. The research note's "~2,996 US"
    was the worldwide sitemap total; the finder yields ~1.3k US in-person +
    ~300 US virtual.
75. **Gam-Anon** — **in-use** (`pipeline/gamanon.py`, 77 meetings). One
    server-rendered Joomla page (`/meeting-directory/us-meetings`); messy
    single-string venue field, state fallback from section headings.
76. **Nar-Anon** — **in-use** (`pipeline/naranon.py`, 623 US meetings of 1,241
    worldwide). WSO group database is a Knack app whose public finder view is an
    open API (`api.knack.com/v1/scenes/scene_18/views/view_26/records`, app id +
    literal key "knack", 100 rows/page). Fragile — every page archived to
    `sources/naranon/` before parsing. The "virtual meetings" scene_57 from the
    research notes is an auth-gated test table.
77. **Overeaters Anonymous** — **in-use** (`pipeline/oa.py`, 376 US meetings).
    `POST oa.org/wp-json/oa-meetings/v1/meetings_search` (928 meetings worldwide
    — the post-pandemic registered list, far below the historic ~6k claim).
    Search HTML converts *all* times to the requested tz, so day/time come from
    a per-meeting detail crawl; stateless online rows can't shard and are
    skipped with a count.
78. **Debtors Anonymous** — **in-use** (`pipeline/debtorsanon.py`, 394 meetings).
    Two server-rendered tables (f2f + virtual; the virtual table needs the
    `mytimezone` param to render) merged per meeting id, plus a detail-page
    crawl for venue/end-time/format.
79. **Adult Children of Alcoholics** — **in-use** (`pipeline/aca.py`, 1,510
    meetings). The wsom REST search (`POST /wp-json/wsom/v1/meeting-search/`)
    *is* drivable without a browser — send scalars only and omit the
    `Focus[]`/`Type[]` arrays entirely (sending them empty filters to zero — the
    failure mode in the research notes); needs the page's X-WP-Nonce + cookies.
    2,070 US rows of 2,991 in the DB; stateless online/phone rows skipped.
80. **SAA** — **held (scope decision)**. ~700 US meetings, plain Drupal views
    pagination with full addresses — technically trivial, but **policy decision
    needed before building** (sensitivity of listing attendees' venue patterns
    for this fellowship). See `docs/research/support-groups-2026-07.md`.

## Treatment & health facilities (federal, public domain)

13. **SAMHSA FindTreatment.gov** — **in-use** (`pipeline/findtreatment.py`,
    17,662 sites). The developer guide's state-ID queries return empty/garbled
    results in practice; a single national radius query (limitType=2, 6,000 km
    from the CONUS centroid, pageSize=2000) returns the full set. VA-run
    facilities that duplicate #46 are dropped by `pipeline/reconcile.py`.
14. **HRSA Data Warehouse** — **in-use** (`pipeline/hrsa.py`, 17,574 sites).
    Daily-refreshed CSV of every FQHC/look-alike service delivery site at a
    stable DD_Files URL. Ryan White HIV care orgs and shortage-area files
    remain unbuilt extensions. Public domain.

## Mental health & crisis

15. **NAMI affiliates** — **in-use** (`pipeline/nami.py`, 801 orgs). Open
    WordPress REST API (`/wp-json/wp/v2/affiliate`) + throttled profile-page
    crawl for the contact `<dl>` (Cloudflare-obfuscated emails decoded). The
    NAMI warmline PDF is its own source now (#81); per-affiliate support-group
    schedules remain a later layer.
16. **988 Lifeline network centers** — **in-use** (`pipeline/lifeline988.py`,
    212 orgs). The crisis-centers-by-state page is fully server-rendered
    (Cloudflare accepts a browser UA — no headless needed). Also emits the
    static national crisis lines (988, Crisis Text Line, Veterans Crisis Line,
    Trevor Project, Trans Lifeline, LGBT National Hotline, National DV Hotline,
    RAINN).
17. **DBSA support groups** — **in-use** (`pipeline/dbsa.py`, 95 orgs).
    Server-rendered per-state pages; chapter-level blocks only (specialty
    groups nested under chapters are meeting-tree material, not orgs).
18. **Mental Health America affiliates** — **in-use** (`pipeline/mha.py`,
    133 orgs). Affiliates sitemap → per-affiliate page crawl.
19. **Clubhouse International directory** — **in-use** (`pipeline/clubhouse.py`,
    253 US orgs). Server-rendered per-letter pages; cf-obfuscated emails decoded;
    non-US entries filtered.
20. **warmline.org** — **probe (secondary)**. Vercel bot-blocked (429s); use as
    cross-check against the NAMI warmline directory (#81).
21. **SPRC state pages** — **planned (low)**. State suicide-prevention contacts;
    enrichment only. **IASP** crisis-centre list — **rejected**: duplicative of 988.
22. **Find A Helpline (ThroughLine)** — **probe**. Real REST API
    (developer.throughlinecare.com), best helpline taxonomy anywhere, but a
    commercial product — license conversation required; do not scrape.

*Added 2026-07:*

81. **NAMI National Warmline Directory (PDF)** — **in-use**
    (`pipeline/warmlines.py`, 84 orgs). Quarterly dated PDF (current: March 9,
    2026), parsed from `pdftotext -layout` by column-center assignment.
    Warmlines are explicitly non-crisis peer lines — records never carry the
    crisis-hotline category.
82. **AFSP chapters** — **in-use** (`pipeline/afsp.py`, 73 orgs). sitemap-0.xml
    lists ~334 `/chapter/` URLs but only ~75 are real chapter roots (identified
    by their "Chapter contact" block); cf-obfuscated emails decoded, state from
    `data-donor-drive-id`. Both Heroku APIs (zip-lookup, support-groups) still
    503 as of 2026-07-20 — the support-group layer stays a probe.

## Grief & bereavement

83. **The Compassionate Friends** — **in-use**
    (`pipeline/compassionatefriends.py`, 438 orgs). The wpsl admin-ajax search
    clamps at 10 results, but the open WP REST API for the `wpsl_stores` post
    type enumerates all ~437 chapters; per-chapter pages embed structured
    location JSON + contact block. Meeting-schedule prose not copied.
84. **Bereaved Parents of the USA** — **in-use** (`pipeline/smallchapters.py`,
    55 orgs). find-a-chapter accordion; leader personal names not copied.
85. **POMC (Parents of Murdered Children)** — **in-use**
    (`pipeline/smallchapters.py`, 44 orgs). Single chapters page.
86. **GriefShare / Church Initiative** — **held (permission-first)**. ToS
    verified 2026-07: **explicit anti-automation terms** — no scraping under
    the fallback policy; one permission email could also unlock the DivorceCare
    sibling directories. Thousands of church-hosted grief groups if granted.

## Housing & shelter

23. **HUD Resource Locator ArcGIS backend** — **in-use** (`pipeline/hud.py`,
    383 CoC orgs + 3,335 PHA sites). Layer 8: CoC contacts (org-level
    phone/email kept, contact-person names never published); layer 1: Public
    Housing Agencies. Keyless, federal public domain.
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
org/hotline/intake contacts only. `pipeline/dvcoalitions.py` enforces a hotline-safe
field allowlist (name, county/city context, hotline phone, website — never street
addresses, even where published).

29. **NNEDV state coalition list** — **in-use** (`pipeline/nnedv.py`, 55 orgs).
    Single-page, org-level, policy-safe. (The Oklahoma entry points at the state
    AG's list, not a coalition, and is skipped.)
30. **ACF FVPSA grantees** — **planned**. 56 state administrators + ~250 tribal
    grantees (public domain); local subgrantee lists live with states, not ACF.
31. **domesticshelters.org** — **rejected**: ToS verified — prohibits scraping and
    content collection. Link-out only.
32. **RAINN local providers** — **probe + rights inquiry**. *Verified:* React SPA
    with internal JSON API at `https://centers.rainn.org/api`; 1,100+ providers.
    RAINN licenses the DB to partners — ask before use. Org/hotline fields only.
33. **VictimConnect** — **probe**. National hotline record now; Resource Map
    backend + rights later.

*Added 2026-07:*

87. **State DV-coalition program directories** — **in-use**
    (`pipeline/dvcoalitions.py`, 785 orgs across 17 coalitions, one source
    record + parser each): NY (nyscadv, 111), NC (92), WA (wscadv, 79), OH
    (odvn, 78), VA (vsdvalliance, 75), PA (pcadv, 59), TN (tncoalition, 54),
    AR (domesticpeace, 42), NJ (njcedv, 39), WY (33), MD (mnadv, 30), PR (paz
    para las mujeres, 17), VT (16), DE (dcadv, 15), LA (lcadv, 15), WV (15),
    KY (zerov, 15). The 2026-07 sweep covered all 56 NNEDV-listed coalitions;
    the rest are JS/map-driven, login-gated SaaS (Coalition Manager), or publish
    no local-program list — revisit opportunistically (CA's CPEDV: JS map, no
    XHR found).

## Food & basic needs

34. **USDA SNAP Retailer Location Data** — **candidate**. *Verified:* **253,894
    retailers** (name, address, lat/lng, store type), ArcGIS FeatureServer
    `services1.arcgis.com/RLQu0rK7h4kbsBq5/.../snap_retailer_location_data/FeatureServer/0`
    + CSV bulk export; updated biweekly. Public domain. (Where to *use* benefits —
    also a strong geocoding anchor.) Largest remaining Tier-1 build.
35. **USDA Summer Meals Site Finder** — **in-use** (`pipeline/summermeals.py`,
    41,941 sites; seasonal). Per-year FeatureServer discovered from the FNS
    ArcGIS org's service list (2026's layer is literally named "…(Testing)" but
    is the live season feed); OPEN sites only, test rows filtered. Public domain.
36. **USDA FDPIR/CSFP administering agencies** — **in-use** (`pipeline/fdpir.py`,
    162 sites). One point-only layer carries both programs; the CSFP half is
    damaged upstream (multi-word state names split across columns, points
    plotted in wrong states) — states reconstructed, coordinates kept only when
    the nearest registry place agrees. Public domain.
37. **WIC clinics (state ArcGIS layers)** — **in-use** (`pipeline/wic.py` +
    `pipeline/curated/wic-layers.yaml`, 8 state layers, 985 sites: WA 209,
    FL 174, OK 114, OR 113, AZ 103, CO 101, NE 90, MD 81). No national dataset
    exists. Not available as of the 2026-07 sweep: TX/NY/IL/GA/NC/PA/OH/MI
    publish nothing statewide; CA publishes vendors only; NM/UT/MT layers are
    stale. signupwic.com remains scrape-hostile; grow the registry as states
    publish.
38. **Feeding America member directory** — **in-use**
    (`pipeline/feedingamerica.py`, 199 orgs). Undocumented JSON API
    (`/ws-api/GetAllOrganizations`, one request); counties-served FIPS lists
    trimmed from the pull. Facts-only re-expression, noted in DATA-RIGHTS.
39. **Pantry level via bank locator platforms (Vivery/AccessFood)** — **rejected
    for scraping** (ToS prohibits); **probe for partnership** (211 Metro Chicago
    precedent). Link2Feed: **rejected** — intake software, not a directory.
    Per-bank locators are heterogeneous — curated registry + isolated parsers if
    pursued (ToS-silent Feeding America members are the fallback pantry path if
    AmpleHarvest never answers).
40. **feedam.org HSDS 3.0 feed** — **probe (rights-limited)**. Open Open Referral
    HSDS API claiming 566k food-assistance locations aggregated from USDA, HRSA,
    state WIC, 211 networks, AmpleHarvest, OSM. DATA-RIGHTS ruling: the CC
    BY-SA share-alike (inconsistently stated) is incompatible with our BY-NC
    umbrella and their right to relicense 211/AmpleHarvest slices is
    questionable — **federal-derived slices only** (which we now pull directly
    anyway); single-maintainer Cloudflare-worker infra. **Archive snapshots
    early.**
41. **AmpleHarvest** — **held (affirmative consent required)**. ToS §3 verified
    2026-07-20: one personal, noncommercial copy licensed; any other
    reproduction/distribution requires **prior written consent** — so NOT
    eligible for the no-reply fallback. Partnership email sent 2026-07-19;
    ingest only on a yes. 8,543 opt-in pantries.
42. **Little Free Pantry map** — **in-use** (`pipeline/littlefreepantry.py`,
    4,836 sites). Entire dataset embedded in-page as a JS array; pantry facts
    only (name, coordinates), submitter personal fields never taken.
43. **Mutual Aid Hub** — **in-use** (`pipeline/mutualaidhub.py`, 886 orgs +
    232 sites). Publicly readable Firestore, **PDDL 1.0** — best license of any
    nonprofit source. Largely COVID-era; every record marked provisional;
    endpoint snapshotted early per DATA-RIGHTS.
44. **National Diaper Bank Network** — **in-use** (`pipeline/ndbn.py`, 251
    orgs). Google My Maps KML export, one request; most placemarks carry no
    coordinates, so state/city come from the description's `Key:: value` pairs.
45. **FoodPantries.org / FoodFinder.us** — **rejected**: ad-supported directories,
    all-rights-reserved, unclear provenance, nothing unique vs. better-rights
    sources.

## Veterans

46. **VA Facilities API (Lighthouse)** — **in-use** (`pipeline/va.py`, 2,094
    sites). Sandbox key serves the real dataset; the documented `/facilities/all`
    bulk route 404s on sandbox, so the module paginates the unfiltered v1
    endpoint. Cemeteries excluded. **CC0/public domain** (per data.gov).
47. **National Resource Directory (nrd.gov)** — **probe**. ~16,000 vetted veteran
    resources; no export; sequential-ID detail pages look enumerable; federal =
    public domain; heavy filtering needed (many are link-level, not site-level).
48. **CVSO rosters (county veteran service officers)** — **probe, per-state**.
    No national roster (NACVSO is members-only); ~35+ state DVA sites publish
    county tables; seed from NASDVA's state links (nasdva.us/resources).
49. **VSO post locators (American Legion ~12.5k, VFW ~6k, DAV)** — **probe**.
    Personify/JSON XHR backends likely; ToS review before scraping. Skip
    third-party aggregators. WWP — rejected (program offices, not services).
    Team RWB — built, see #88.

*Added 2026-07:*

88. **Team Red, White & Blue** — **in-use** (`pipeline/teamrwb.py`, 202 orgs).
    find-your-chapter renders the full list inline; city-level entries carry no
    street address (that is how the org publishes them); members-site group
    link as website.

## Older adults

50. **Eldercare Locator (ACL)** — **held (license decision)**. 617 Area Agencies
    on Aging + 270+ Title VI Native aging programs; **ODbL-licensed** per
    data.gov — share-alike/attribution obligations must be reconciled with the
    CC BY-NC umbrella before any ingest (see DATA-RIGHTS). Decision unblocks
    the seniors category — our weakest (8% covered per the BMF gap audit,
    `docs/research/bmf-gap-audit-2026-07.md`). Probe the search backend or
    request the dataset from ACL once decided.
51. **AGID/ACL State Profiles** — **rejected (corrected finding)**. The 2026-07
    sweep verified the state profiles render program *statistics*, not AAA
    directories — Eldercare Locator (#50) remains the AAA route.

*Added 2026-07:*

89. **Alzheimer's Association chapters** — **in-use** (`pipeline/alz.py`, 78
    orgs). `POST alz.org/api/chapter/search` accepts `{"state": "XX"}` — one
    POST per state, deduped by chapter URL; multi-state chapters noted via
    regional service_area. Facts-only, attributed.

## Disability & condition support

90. **The Arc chapters** — **in-use** (`pipeline/thearc.py`, 564 orgs). Dedicated
    chapter sitemap (~578 pages), uniform Contact textblock per page; unparseable
    pages skipped and reported, not fatal.
91. **Autism Society affiliates** — **in-use** (`pipeline/smallchapters.py`,
    70 orgs). Accordion on the contact-us page.
92. **National MS Society self-help groups** — **in-use**
    (`pipeline/mssociety.py`, 174 meetings). Salesforce LWR SPA, but fully
    reachable without a browser: the shell HTML embeds the route manifest
    (~239 self-help-group routes) and page content lives in a *public* Sanity
    dataset (one GROQ query); route→doc joined via name match with the LWR
    view-JS `sanityPageId` as exact fallback. Free-text schedules parsed;
    unparseable ("contact group leader") skipped with a count.
93. **Epilepsy Foundation** — **probe (blocked)**. Full bot wall — an
    interactive challenge (403 to everything non-browser); headless capture if
    pursued.

## LGBTQ+

52. **PFLAG chapters** — **in-use** (`pipeline/pflag.py`, 323 orgs). All
    chapters embedded as a JSON string in the page's inline `tmscripts` config —
    one GET, no API.
53. **CenterLink LGBTQ+ centers** — **in-use** (`pipeline/centerlink.py`, 316
    orgs). WebLink/MemberClicks "Atlas" SPA; the listing/search API needs a
    short-lived SPA-minted JWT, so capture is a documented one-shot Playwright
    step (`--capture`) that replays the paged search in-context; normal runs
    build from cache. Upstream quirk: street addresses are masked ("*") for
    nearly all listings — city/state/zip only.
54. **National LGBTQ+ hotlines** — **in-use** (folded into
    `pipeline/lifeline988.py`'s static national set, #16: Trevor Project, Trans
    Lifeline, LGBT National Hotline).
55. **LGBT Near Me** — **probe (partnership)**. Claims 22,000+ resources; ZIP-radius
    UI only; open public submissions (quality risk); ask for export.
56. **OutCare Health** — **rejected**: ToS explicitly prohibits scraping with
    liquidated damages. **GLMA directory** — **rejected (soft)**: unvetted
    individual providers, wrong granularity.

*Added 2026-07:*

94. **TransFamilies online groups** — **in-use** (`pipeline/smallchapters.py`,
    13 orgs). The Events Calendar REST feed; recurring instances deduped by
    title (67 events → ~12 groups). Complements PFLAG.
95. **Glisten chapters** — **in-use** (`pipeline/smallchapters.py`, 16 orgs).
    our-chapters accordion.

## Youth & family

57. **Head Start locations (ACF)** — **in-use** (`pipeline/headstart.py`,
    16,096 sites). Public ArcGIS layer, paged by OBJECTID; "Closed" rows
    dropped, "Open"/"Not Reported" kept (both funded). Public domain.
58. **Boys & Girls Clubs (~4,700) / YMCA (~2,600)** — **probe**. Both need headless
    XHR capture of their map locators.
59. **Big Brothers Big Sisters** — **probe**. Legacy ASP.NET ZIP lookup (~230
    agencies); coarse ZIP sweep.
60. **Childcare.gov** — **planned (crosswalk)**. No national provider dataset;
    gateway to ~56 state search systems (per-state modules someday). Child Care
    Aware's 500k-program dataset is proprietary — **rejected**. CCR&R agency list
    (~400 referral agencies) — **probe**.

*Added 2026-07:*

96. **La Leche League USA** — **in-use** (`pipeline/lllusa.py`, 382 orgs).
    WP Go Maps open REST markers endpoint, one GET (~396 markers); free-text
    addresses parsed best-effort with nearest-place fallback; leader-contact
    prose (personal names/emails) never copied.
97. **Postpartum Support International** — **in-use** (`pipeline/psi.py`, 44
    meetings). ~50 free specialized online groups on server-rendered WordPress
    pages; free-text schedules parsed into day+time with the recurrence phrase
    kept as a note; all shard under us/online.

## Legal aid

61. **LSC grantees** — **in-use** (`pipeline/lsc.py`, 128 orgs). The public
    grantee page only links Tableau embeds; the machine source is the Find
    Legal Aid tool's static `Programs.json` (one entry per service area, state
    from the Serv_Area_ID prefix). Authoritative for civil legal aid.
62. **EOIR pro bono providers (immigration)** — **in-use** (`pipeline/eoir.py`,
    125 orgs). Quarterly two-column PDF parsed via `pdftotext -layout` with
    modal-indent column splitting; private-attorney entries skipped; providers
    dedupe across courts. Public domain; July 2026 edition current.
63. **Immigration Advocates Network directory** — **held (permission clock)**.
    900+ nonprofit immigration legal providers, best-in-class; partnership
    email sent 2026-07-19 (they already syndicate to partners). No reuse or
    scraping restrictions found (verified 2026-07-20), so no reply by
    **2026-08-09** → facts-only ingestion, throttled, attributed.
64. **LawHelp.org portals** — **planned (gap-fill)**. ~20 statewide portals,
    heterogeneous. **ABA Free Legal Answers** — planned, low (state-level virtual
    clinic records). The BMF gap audit flags legal as 38.5% covered — WI
    (Madison, Milwaukee) is the loudest single-state miss.

## Utility & financial assistance

65. **LIHEAP Clearinghouse office directory** — **in-use** (`pipeline/liheap.py`,
    2,712 sites). Statewide coverage means enumerating every county (~3.2k
    requests at the mandatory 1 req/s — an hour cold, instant from cache);
    offices dedupe on (name, city) with county lists folded into descriptions.
    Quirk: the host omits its Entrust TLS intermediate; the module chases the
    AIA URL once and installs a trusting opener. Public domain.
66. **Community Action Agencies** — **planned**. ~1,000 CAAs;
    communityactionpartnership.com WP locator (probe ajax) + ACF association
    contacts page (PD). BMF audit: financial-assistance is 46% covered — NFCC
    member agencies are the other candidate here.
67. **St. Vincent de Paul / Catholic Charities** — CCUSA **in-use**
    (`pipeline/ccusa.py`, 169 orgs — whole agency locator dataset in an inline
    JSON blob, one GET; three territory entries patched). SVdP: **probe**
    (~4,400 conferences, probe locator). Salvation Army: built — see #98.
    Per-agency program sites remain a later hyper-local layer.

*Added 2026-07:*

98. **Salvation Army USA** — **in-use** (`pipeline/salvationarmy.py`, 2,141
    sites, multi-category). The location finder is a Zesty.io site whose search
    runs client-side over the CMS "instant" content API — five unauthenticated
    GETs return the complete dataset (~3.4k locations + lookup models). Kept:
    corps centers, service units, shelters, transitional housing, ARC/Harbor
    Light rehab, food pantries, DV centers, Kroc/youth/senior/health/child-care
    sites. Skipped: thrift stores, drop boxes, admin, camps, worship/retail-only.
    Rights: no site-wide ToS exists (verified 2026-07 — the only "legal" page is
    an Indiana-Division copyright notice covering page materials, not facts);
    robots.txt allows all; same API their own front end calls. Facts-only,
    attributed.

## Cross-cutting mega-datasets

68. **IRS Exempt Organizations BMF** — **candidate (discovery seed, not
    directory)**. ~**1.98M nonprofits** with EIN, address, **NTEE codes**;
    monthly CSVs at irs.gov/pub/irs-soi/. Used for the July 2026 coverage gap
    audit (`docs/research/bmf-gap-audit-2026-07.md` — 172k service-relevant
    orgs mapped against our records; seniors/crisis/veterans/financial/legal
    flagged weakest). Caveats: mailing addresses not service sites, includes
    shells/defunct orgs. Never publish directly. Public domain.
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

## Build status (2026-07-20) and remaining order

Registry: **98 entries** — 55 in-use, 3 candidate, 8 planned, 15 probe, 7 held,
10 rejected — expanding to 117 source records on disk. Built dataset: 109,770
sites, 69,627 meetings, 7,133 orgs.

Done: the entire original Tier 1 except SNAP retailers and Al-Anon (held), all
of Tier 2, and most of Tier 3 — the TSML registry (45 feeds), the headless
probes that mattered (CenterLink, SMART — turned out passive, Salvation Army,
ACA, MS Society), the round-2 fellowship sweep (GA, Gam-Anon, Nar-Anon, OA, DA,
LifeRing), the chapter-directory sweep (AFSP, Alz, Arc, Autism Society, Glisten,
BPUSA, POMC, TransFamilies, LLL, TCF, Team RWB, DBSA, warmlines, 988), WIC (8
state layers), FDPIR, and 17 state DV coalitions.

Remaining, in order:

Tier A — verified candidates, ready to build: SNAP retailers (34, biggest
remaining bulk), ACF RHY (26) + FVPSA (30) grantees, HUD HIC as QA (24).

Tier B — permission/decision clocks: Al-Anon (6) and IAN (63) fallback date
**2026-08-09**; AmpleHarvest (41) on affirmative consent only; the 17
restricted-TSML sharing-key emails (docs/outreach.md batch 2 — send them);
decisions owed on Eldercare ODbL (50) and SAA scope (80).

Tier C — probes, prioritized by the BMF gap audit: seniors (Eldercare decision
unblocks a near-total blind spot), more DV coalition states (MI, GA next),
RAINN rights ask (32), veterans layer (CVSO 48 / VSO posts 49 / NRD 47),
financial (CAAs 66, NFCC), legal (LawHelp 64), OIAA pagination (5), BGCA/YMCA
(58), BBBS (59), NSPN (27), ThroughLine (22).

Archive-early (fragile endpoints): Mutual Aid Hub Firestore, feedam.org worker
API, Feeding America ws-api, NDBN KML, Al-Anon storelocator JSON, Nar-Anon
Knack API, ACA wsom API (session-bound nonce).
