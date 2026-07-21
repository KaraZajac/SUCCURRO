# Feeding America member-bank pantry/agency locator survey (2026-07)

Research-only. No pipeline code, no `data/` writes. Classifies all 198 Feeding
America member food banks (the `us/feeding-america` parent record is the 199th
`data/orgs` file and is excluded) by the platform each uses for its pantry/agency
locator and by whether a full unauthenticated dump is reachable — the same
exercise `pipeline/dvcoalitions.py` did for DV coalitions.

Method: read each bank's `AgencyURL` from the cached Feeding America
`GetAllOrganizations` pull (`sources/feedingamerica/`), joined to its
`data/orgs/**` record. Fetched every locator page throttled (project UA, browser-UA
fallback on WAF codes); for the ~85 banks whose landing page was a hub, followed one
"find food / pantry / locator" link (stage 2); re-classified by platform
fingerprint; then curl-probed visible candidate endpoints. 188/198 landing pages
returned 200; 9 `AgencyURL`s are dead (404, re-crawled from the homepage) and 1
(`va/feed-more`) sits behind a 403 WAF. **45 endpoints were probed with curl; 43
returned an open JSON/XML/KML dump.** Counts marked `*` are plugin page-size
defaults (10/20/25/50) — the endpoint is open but the full network needs a
point-grid sweep or a `max_results` override, so those are a floor.

## Headline numbers

| Bucket | Banks | Notes |
|---|---|---|
| **Vivery / AccessFood** (REJECTED per DATA-RIGHTS) | **67** | detected via `cdn.vivery.org`, `accessfood-widget`, `food-access-widget-cdn`, or `pantrynet.org`; all genuine (not incidental string hits) |
| **Verified open endpoint** (curl-confirmed dump) | **43** | 5,448 agency records summed (floor; 12 are page-capped) |
| **Scrapeable — static HTML list** (server-rendered table/list) | 13 | e.g. Oregon FB, Maryland FB, Mid-Ohio, Contra Costa "food by city" |
| **Scrapeable — inline-JSON map** (full dataset embedded in page, Little-Free-Pantry style) | 6 | Cleveland 404 pts, Ozarks 274 pts, etc. |
| **Likely scrapeable** (known platform, endpoint not yet verified) | 9 | ArcGIS-embed / StoreRocket / wpsl nonce-gated |
| **Needs headless / undetermined** | 58 | custom JS maps (Wix `_api`, Squarespace, mapbox/leaflet/gmaps runtime XHR), phone/PDF-only, or locator not found statically |
| **Rejected — intake software** (Link2Feed) | 1 | `mi/...` not a public directory |
| **AgencyURL dead / WAF-blocked** | 1 | `va/feed-more` (403) |

**Cleanly scrapeable today (no headless, rights-clear): 43 verified + 13
static-HTML + 6 inline-JSON = 62 banks.** Adding the 9 "likely" (ArcGIS/StoreRocket
resolves are mechanical) brings it to ~71 banks — well over a third of the network,
and none of them Vivery.

## Estimated reachable pantry-agency records

- **Verified-open subset (43 banks): 5,448 records** curl-confirmed, of which
  ~5,050 are from non-capped full dumps. Un-capping the 12 page-limited store
  locators (LA Regional, Orange County, Philabundance, St. Louis, RI, Coastal
  Bend, Lehigh Valley, Golden Harvest, FeedMore WNY, Regional NENY, SE-NC,
  E. Michigan) via a grid sweep plausibly adds another ~2,000–4,000.
- **Static-HTML + inline-JSON banks (19): est. ~3,000–4,000** more (Cleveland
  alone embeds ~400; large state banks like Oregon and Maryland list hundreds).
- **Grand estimate for the non-Vivery, non-headless reachable set: ~11,000–14,000
  pantry-agency records** across ~62–71 banks. The 67 Vivery banks (easily the
  largest share of the ~60k national agency count) stay behind the link-out wall
  per DATA-RIGHTS unless the partnership ask lands. A later headless pass over the
  58 "undetermined" banks would add several thousand more.

## Anti-scrape ToS findings

Spot-checked the obvious terms/legal link on each bank (219 terms pages fetched).
Tiering matters — most "hits" are generic CMS boilerplate, and the bare word
"harvest" is a false positive (many banks are named "…Harvest"), so those were
dropped.

- **STRONG — explicit anti-automation clause (4):** `md/maryland-food-bank`
  ("You agree not to use automated means to scrape data from the Site"),
  `oh/freestore-foodbank`, `mi/food-bank-of-eastern-michigan`,
  `ca/food-bank-for-monterey-county`. Treat these as **permission-first**
  (AmpleHarvest-class), even though facts are not copyrightable — mirrors the
  DATA-RIGHTS posture on affirmative consent. Notably Maryland is *also* one of
  the static-HTML "scrapeable" banks; the ToS, not the tech, is the blocker.
- **Content-reuse consent (4):** `ca/alameda-county-community-food-bank`,
  `fl/treasure-coast-food-bank`, `ia/food-bank-of-iowa`,
  `tx/food-bank-of-west-central-texas` — "prior written permission" to reprint
  text/logos/images (not a data-scraping ban). Facts-only re-expression stays
  defensible, but cite carefully.
- **Boilerplate no-robots (13):** stock "no robots/spiders/crawlers" template
  language (Foodlink, Roadrunner, Kansas, Tarrant, Philabundance, E. Illinois,
  Regional NENY, S. Dakota, S. Texas, Harry Chapin, Mountaineer, S. Wisconsin,
  Find). Common CMS ToS; not a targeted prohibition. Note none of the Vivery ToS
  needed re-checking — those are rejected on the platform ToS already.
- The remaining ~170 banks surfaced no anti-scrape terms on the obvious link.

## Recommended registry-module design

Mirror `pipeline/dvcoalitions.py` + `pipeline/curated/feeds.yaml` exactly — this is
the same "heterogeneous per-member locators" shape, and the AA-TSML `feeds.yaml`
registry is the closest working precedent.

1. **`pipeline/curated/foodbank-locators.yaml`** — one hand-maintained row per
   scrapeable bank, keyed to its `data/orgs` id:
   ```yaml
   - {id: me/good-shepherd-food-bank, platform: wpsl, state: me,
      endpoint: 'https://www.gsfb.org/wp-admin/admin-ajax.php?action=store_search&autoload=1'}
   - {id: ky/feeding-america-kentucky-s-heartland, platform: wpgmza, state: ky,
      endpoint: 'https://feedingamericaky.org/wp-json/wpgmza/v1/markers'}
   - {id: dc/capital-area-food-bank, platform: arcgis, state: dc,
      endpoint: 'https://services.arcgis.com/oCjyzxNy34f0pJCV/arcgis/rest/services/Get_Help_Map_Source_Data/FeatureServer/0'}
   ```
   Carry `ua: browser` where the WAF needs it, a `capped: true` flag where a grid
   sweep is required, and a `tos: permission-first` flag on the 4 STRONG banks so
   the emitter can suppress them until consent (same gate as AmpleHarvest).
2. **`pipeline/foodbanklocators.py`** — one `--all` runner, a small parser **per
   platform family** (not per bank), since only ~8 platforms cover every
   scrapeable member:
   - `wpsl` (WP Store Locator) — 17 banks — `admin-ajax.php?action=store_search&autoload=1` → JSON array
   - `wpgmza` (WP Go Maps) — 8 — `/wp-json/wpgmza/v1/markers` → JSON array
   - `asl` (Agile Store Locator) — 5 — `admin-ajax.php?action=asl_load_stores&load_all=1` → JSON array
   - `slp` (Store Locator Plus) — 6 — `admin-ajax.php?action=csl_ajax_onload` → `{response:[...]}`
   - `storepoint` — 3 — `api.storepoint.co/v1/{id}/locations` → `{results:{locations:[...]}}`
   - `mymaps` (Google My Maps) — 6 — `maps/d/kml?mid={mid}&forcekml=1` → KML placemarks
   - `arcgis` — 4 — FeatureServer `/query?where=1=1&outFields=*&f=json`
   - `storerocket` — 2, `superstorefinder` — 1 (per-bank tail)
   Each parser owns its records and re-runs replace per bank (the dvcoalitions
   "each coalition owns exactly its records" rule). Emit `categories: [food-pantry]`,
   `parent_org` set to the bank's `id`, facts-only (name/address/phone/hours/geo),
   one `sources` entry `<bank-domain>/agency-locator` + archive + retrieval date.
3. **Records to write:** street addresses ARE published for pantries and are safe
   to record (unlike the DV-confidential rule) — the field allowlist can be the
   normal org schema. Keep the counties-served / eligibility text only where the
   source gives it cleanly.
4. **Snapshot-early** the ArcGIS and Storepoint feeds (fragile, single-maintainer),
   per the DATA-RIGHTS note on Mutual Aid Hub / feedam.

## Top-20 easiest wins (ordered)

Ranked by agencies delivered × single-request simplicity, minus ToS friction.
`*` = page-capped count (floor). All verified open with curl this survey.

| # | Bank | State | Platform | Endpoint | Est. agencies |
|---|---|---|---|---|---|
| 1 | Good Shepherd Food Bank | ME | WP Store Locator | `gsfb.org/wp-admin/admin-ajax.php?action=store_search&autoload=1` | 618 |
| 2 | Feeding America Kentucky's Heartland | KY | WP Go Maps | `feedingamericaky.org/wp-json/wpgmza/v1/markers` | 423 |
| 3 | Feeding America Eastern Wisconsin | WI | WP Go Maps | `.../wp-json/wpgmza/v1/markers` | 348 |
| 4 | Capital Area Food Bank | DC | ArcGIS | `services.arcgis.com/oCjyzxNy34f0pJCV/.../Get_Help_Map_Source_Data/FeatureServer/0` | 330 |
| 5 | Food Bank of Eastern Oklahoma | OK | WP Go Maps | `.../wp-json/wpgmza/v1/markers` | 274 |
| 6 | The Idaho Foodbank | ID | Agile Store Locator | `idahofoodbank.org/wp-admin/admin-ajax.php?action=asl_load_stores&load_all=1` | 262 |
| 7 | Food Bank of Western Massachusetts | MA | WP Store Locator | `.../admin-ajax.php?action=store_search&autoload=1` | 248 |
| 8 | Lowcountry Food Bank | SC | Agile Store Locator | `.../admin-ajax.php?action=asl_load_stores&load_all=1` | 208 |
| 9 | Second Harvest of Coastal Georgia | GA | WP Store Locator | `.../admin-ajax.php?action=store_search&autoload=1` | 207 |
| 10 | Second Harvest FB of East Tennessee | TN | Google My Maps | `maps/d/kml?mid=16ei4cVPP4mTcCaEocPz3eV4Pd3qm5ZA&forcekml=1` | 184 |
| 11 | Food Bank for the Heartland | NE | Storepoint | `api.storepoint.co/v1/161e1dcd91b7b8/locations` | 180 |
| 12 | Food Bank of South Jersey | NJ | Agile Store Locator | `.../admin-ajax.php?action=asl_load_stores&load_all=1` | 165 |
| 13 | FOOD Share (Ventura) | CA | Agile Store Locator | `.../admin-ajax.php?action=asl_load_stores&load_all=1` | 155 |
| 14 | Hawaii Foodbank | HI | Google My Maps | `maps/d/kml?mid=1U3q_j27iwLeAJqzyMuMptu6U8QIdh6vx&forcekml=1` | 141 |
| 15 | Toledo Northwestern Ohio Food Bank | OH | Storepoint | `api.storepoint.co/v1/1662a5ad8a1488/locations` | 132 |
| 16 | Fulfill (Monmouth & Ocean) | NJ | Agile Store Locator | `.../admin-ajax.php?action=asl_load_stores&load_all=1` | 127 |
| 17 | Channel One Regional Food Bank | MN | WP Go Maps | `.../wp-json/wpgmza/v1/markers` | 89 |
| 18 | Harvest Hope Food Bank | SC | ArcGIS | `services1.arcgis.com/x5wCko8UnSi4h0CB/.../_Food_Pantry_Map_Data_May_2026/FeatureServer/0` | 89 |
| 19 | Community Harvest FB of NE Indiana | IN | WP Go Maps | `.../wp-json/wpgmza/v1/markers` | 64 |
| 20 | Food Bank of West Central Texas | TX | Google My Maps | `maps/d/kml?mid=15jt8EPmUrPHFQsKt6ESIDVGXgz3fqVs&forcekml=1` | 66 (ToS: consent) |

Fast-follow tier (verified, not in top-20): St. Louis Area FB `*`, Rhode Island
Community FB `*`, Regional FB of NENY `*`, Coastal Bend `*`, Lehigh Valley `*`,
River Valley (AR, 92), Treasure Coast (FL, 69), Golden Harvest (GA) `*`, plus the
inline-JSON set (Cleveland ~404, Ozarks 274) and the static-HTML state banks
(Oregon, Mid-Ohio, Blue Ridge) — all no-headless.

## Uncertainty / honesty notes

- **12 verified counts are plugin page-caps**, marked `*` in the table. The dump is
  open; the number is a floor. Confirmed for Philabundance/LA Regional (their wpsl
  returns only the nearest 10 even at radius 500 — likely their own settings cap,
  not the true agency list).
- **58 "needs-headless" banks are genuinely undetermined**, not confirmed empty.
  Several almost certainly hide an open endpoint behind a runtime XHR — e.g. DC
  Capital Area *looked* undetermined until its `experience.arcgis.com` iframe was
  resolved to a 330-record FeatureServer. A headless/iframe-follow pass would
  likely convert 10–20 of these (the ArcGIS-embed, mapbox, and Wix-`_api` ones)
  into verified wins. Wix `_api/…/businesses` and Squarespace pages are the least
  promising.
- **wpsl nonce-gating:** two wpsl banks (Feeding Westchester, SE Virginia
  `foodbankonline.org`) returned empty from `store_search` — likely a nonce/token
  requirement; marked "likely" not verified.
- **StoreRocket** (Island Harvest NY, Middle TN): platform confirmed but the public
  API path (`api.storerocket.io/api/user/{id}/locations`) 404'd for the extracted
  id — needs the widget's exact key; left as "likely".
- Record counts are the endpoint's returned feature count, not a claim about active
  pantries; some maps include the bank's own warehouses (e.g. `nd/great-plains` = 2,
  `va/feeding-southwest-virginia` = 3 markers — those maps are the bank's sites, not
  an agency network, and were kept out of the top-20).

## Full classification table

Est. agencies `*` = page-capped floor. Verified endpoints are curl-confirmed this
survey; empty endpoint cell = platform known but not probed, or undetermined.

| Bank | St | Locator platform | Verified endpoint | Est. agencies | ToS | Verdict |
|---|---|---|---|---|---|---|
| Food Bank of Alaska, Inc. | AK | custom/JS map (undetermined) |  |  |  | needs-headless |
| Community Food Bank of Central Alabama | AL | Vivery/AccessFood |  |  |  | BLOCKED (Vivery) |
| Feeding the Gulf Coast | AL | custom/JS map (undetermined) |  |  |  | needs-headless |
| Food Bank of North Alabama | AL | custom/JS map (undetermined) |  |  |  | needs-headless |
| Heart of Alabama Food Bank | AL | ArcGIS FeatureServer |  |  |  | scrapeable (likely) |
| Arkansas Foodbank | AR | Vivery/AccessFood |  |  |  | BLOCKED (Vivery) |
| Food Bank of Northeast Arkansas | AR | Vivery/AccessFood |  |  |  | BLOCKED (Vivery) |
| Harvest Regional Food Bank, Inc. | AR | custom/JS map (undetermined) |  |  |  | needs-headless |
| Northwest Arkansas Food Bank | AR | Vivery/AccessFood |  |  |  | BLOCKED (Vivery) |
| River Valley Regional Food Bank | AR | Store Locator Plus | www.rvrfoodbank.org/wp-admin/admin-ajax.php?action=csl_ajax_onload… | 92 |  | SCRAPEABLE (verified) |
| Community Food Bank of Southern Arizona | AZ | Vivery/AccessFood |  |  |  | BLOCKED (Vivery) |
| St. Mary's Food Bank | AZ | Vivery/AccessFood |  |  |  | BLOCKED (Vivery) |
| United Food Bank | AZ | Vivery/AccessFood |  |  |  | BLOCKED (Vivery) |
| Yuma Community Food Bank | AZ | Vivery/AccessFood |  |  |  | BLOCKED (Vivery) |
| Alameda County Community Food Bank | CA | custom/JS map (undetermined) |  |  | consent | needs-headless |
| Central California Food Bank | CA | Super Store Finder |  |  |  | scrapeable (likely) |
| FIND Regional Food Bank | CA | custom/JS map (undetermined) |  |  | boiler | needs-headless |
| Feeding America Riverside / San Bernardino Counties | CA | custom/JS map (undetermined) |  |  |  | needs-headless |
| Feeding San Diego | CA | Storepoint |  |  |  | scrapeable (likely) |
| Feeding the Foothills | CA | custom/JS map (undetermined) |  |  |  | needs-headless |
| Food Bank for Monterey County | CA | MapSVG |  |  | **STRONG** | needs-headless |
| Food Bank of Contra Costa and Solano | CA | static HTML list |  |  |  | SCRAPEABLE (html) |
| Food Share, Inc. | CA | Agile Store Locator | foodshare.com/wp-admin/admin-ajax.php?action=asl_load_stores&load_… | 155 |  | SCRAPEABLE (verified) |
| Foodbank of Santa Barbara County | CA | Vivery/AccessFood |  |  |  | BLOCKED (Vivery) |
| Los Angeles Regional Food Bank | CA | WP Store Locator | www.lafoodbank.org/wp-admin/admin-ajax.php?action=store_search&aut… | 10* |  | SCRAPEABLE (verified) |
| Redwood Empire Food Bank | CA | Vivery/AccessFood |  |  |  | BLOCKED (Vivery) |
| SF-Marin Food Bank | CA | custom/JS map (undetermined) |  |  |  | needs-headless |
| Second Harvest Food Bank Santa Cruz County | CA | Vivery/AccessFood |  |  |  | BLOCKED (Vivery) |
| Second Harvest Food Bank of Orange County | CA | WP Store Locator | feedoc.org/wp-admin/admin-ajax.php?action=store_search&autoload=1 | 10* |  | SCRAPEABLE (verified) |
| Second Harvest of Silicon Valley | CA | custom/JS map (undetermined) |  |  |  | needs-headless |
| Second Harvest of the Greater Valley | CA | Vivery/AccessFood |  |  |  | BLOCKED (Vivery) |
| Care and Share Food Bank | CO | Vivery/AccessFood |  |  |  | BLOCKED (Vivery) |
| Community Food Share | CO | Vivery/AccessFood |  |  |  | BLOCKED (Vivery) |
| Food Bank for Larimer County | CO | Vivery/AccessFood |  |  |  | BLOCKED (Vivery) |
| Food Bank of the Rockies | CO | Vivery/AccessFood |  |  |  | BLOCKED (Vivery) |
| Weld Food Bank | CO | Vivery/AccessFood |  |  |  | BLOCKED (Vivery) |
| Connecticut Foodshare | CT | custom/JS map (undetermined) |  |  |  | needs-headless |
| Capital Area Food Bank | DC | ArcGIS FeatureServer | services.arcgis.com/oCjyzxNy34f0pJCV/arcgis/rest/services/Get_Help… | 330 |  | SCRAPEABLE (verified) |
| Food Bank of Delaware | DE | static HTML list |  |  |  | SCRAPEABLE (html) |
| All Faiths Food Bank | FL | Vivery/AccessFood |  |  |  | BLOCKED (Vivery) |
| Feeding Northeast Florida | FL | custom/JS map (undetermined) |  |  |  | needs-headless |
| Feeding South Florida | FL | custom/JS map (undetermined) |  |  |  | needs-headless |
| Feeding Tampa Bay | FL | Vivery/AccessFood |  |  |  | BLOCKED (Vivery) |
| Harry Chapin Food Bank of Southwest Florida | FL | Vivery/AccessFood |  |  | boiler | BLOCKED (Vivery) |
| Second Harvest Food Bank Of Central Florida, Inc. | FL | custom/JS map (undetermined) |  |  |  | needs-headless |
| Second Harvest of the Big Bend | FL | Vivery/AccessFood |  |  |  | BLOCKED (Vivery) |
| Treasure Coast Food Bank | FL | Store Locator Plus | stophunger.org/wp-admin/admin-ajax.php?action=csl_ajax_onload&lat=… | 69 | consent | SCRAPEABLE (verified) |
| Atlanta Community Food Bank | GA | custom/JS map (undetermined) |  |  |  | needs-headless |
| Feeding the Valley Food Bank | GA | WP Store Locator | feedingthevalley.org/wp-admin/admin-ajax.php?action=store_search&a… | 106 |  | SCRAPEABLE (verified) |
| Food Bank of Northeast Georgia | GA | Vivery/AccessFood |  |  |  | BLOCKED (Vivery) |
| Golden Harvest Food Bank | GA | Store Locator Plus | goldenharvest.org/wp-admin/admin-ajax.php?action=csl_ajax_onload&l… | 50* |  | SCRAPEABLE (verified) |
| Middle Georgia Community Food Bank | GA | Vivery/AccessFood |  |  |  | BLOCKED (Vivery) |
| Second Harvest of Coastal Georgia | GA | WP Store Locator | helpendhunger.org/wp-admin/admin-ajax.php?action=store_search&auto… | 207 |  | SCRAPEABLE (verified) |
| Second Harvest of South Georgia | GA | WP Maps Pro |  |  |  | needs-headless |
| Hawaii Foodbank | HI | Google My Maps | www.google.com/maps/d/kml?mid=1U3q_j27iwLeAJqzyMuMptu6U8QIdh6vx&fo… | 141 |  | SCRAPEABLE (verified) |
| Food Bank of Iowa | IA | static HTML list |  |  | consent | SCRAPEABLE (html) |
| HACAP Food Reservoir | IA | custom/JS map (undetermined) |  |  |  | needs-headless |
| Northeast Iowa Food Bank | IA | Vivery/AccessFood |  |  |  | BLOCKED (Vivery) |
| River Bend Food Bank | IA | Vivery/AccessFood |  |  |  | BLOCKED (Vivery) |
| The Idaho Foodbank | ID | Agile Store Locator | idahofoodbank.org/wp-admin/admin-ajax.php?action=asl_load_stores&l… | 262 |  | SCRAPEABLE (verified) |
| Central Illinois Foodbank | IL | custom/JS map (undetermined) |  |  |  | needs-headless |
| Eastern Illinois Foodbank | IL | Vivery/AccessFood |  |  | boiler | BLOCKED (Vivery) |
| Greater Chicago Food Depository | IL | Vivery/AccessFood |  |  |  | BLOCKED (Vivery) |
| Northern Illinois Food Bank | IL | Vivery/AccessFood |  |  |  | BLOCKED (Vivery) |
| Community Harvest Food Bank of Northeast Indiana, Inc. | IN | WP Go Maps (wpgmza) | www.communityharvest.org/wp-json/wpgmza/v1/markers | 64 |  | SCRAPEABLE (verified) |
| Food Bank of Northern Indiana | IN | inline-JSON map |  |  |  | SCRAPEABLE (inline-json) |
| Food Bank of Northwest Indiana | IN | Vivery/AccessFood |  |  |  | BLOCKED (Vivery) |
| Food Finders Food Bank | IN | Vivery/AccessFood |  |  |  | BLOCKED (Vivery) |
| Gleaners Food Bank of Indiana, Inc. | IN | Vivery/AccessFood |  |  |  | BLOCKED (Vivery) |
| Hoosier Hills Food Bank | IN | custom/JS map (undetermined) |  |  |  | needs-headless |
| Second Harvest Food Bank of East Central Indiana | IN | Vivery/AccessFood |  |  |  | BLOCKED (Vivery) |
| Terre Haute Catholic Charities Foodbank | IN | custom/JS map (undetermined) |  |  |  | needs-headless |
| Tri-State Food Bank, Inc. | IN | Vivery/AccessFood |  |  |  | BLOCKED (Vivery) |
| Kansas Food Bank | KS | custom/JS map (undetermined) |  |  | boiler | needs-headless |
| Dare to Care Food Bank | KY | inline-JSON map |  |  |  | SCRAPEABLE (inline-json) |
| Feeding America, Kentucky's Heartland | KY | WP Go Maps (wpgmza) | feedingamericaky.org/wp-json/wpgmza/v1/markers | 423 |  | SCRAPEABLE (verified) |
| Gods Pantry Food Bank, Inc. | KY | static HTML list |  |  |  | SCRAPEABLE (html) |
| Food Bank of Central Louisiana | LA | Vivery/AccessFood |  |  |  | BLOCKED (Vivery) |
| Food Bank of Northeast Louisiana | LA | WP Store Locator | foodbanknela.org/wp-admin/admin-ajax.php?action=store_search&autol… | 46 |  | SCRAPEABLE (verified) |
| Food Bank of Northwest Louisiana | LA | custom/JS map (undetermined) |  |  |  | needs-headless |
| Greater Baton Rouge Food Bank | LA | Vivery/AccessFood |  |  |  | BLOCKED (Vivery) |
| Second Harvest Food Bank of Greater New Orleans and Acadiana | LA | custom/JS map (undetermined) |  |  |  | needs-headless |
| Food Bank of Western Massachusetts | MA | WP Store Locator | www.foodbankwma.org/wp-admin/admin-ajax.php?action=store_search&au… | 248 |  | SCRAPEABLE (verified) |
| The Greater Boston Food Bank | MA | Vivery/AccessFood |  |  |  | BLOCKED (Vivery) |
| Worcester County Food Bank | MA | WP Store Locator | foodbank.org/wp-admin/admin-ajax.php?action=store_search&autoload=… | 78 |  | SCRAPEABLE (verified) |
| Maryland Food Bank | MD | static HTML list |  |  | **STRONG** | SCRAPEABLE (html) |
| Good Shepherd Food Bank | ME | WP Store Locator | www.gsfb.org/wp-admin/admin-ajax.php?action=store_search&autoload=… | 618 |  | SCRAPEABLE (verified) |
| Feeding America West Michigan | MI | inline-JSON map |  |  |  | SCRAPEABLE (inline-json) |
| Food Bank of Eastern Michigan | MI | Store Locator Plus | www.fbem.org/wp-admin/admin-ajax.php?action=csl_ajax_onload&lat=39… | 50* | **STRONG** | SCRAPEABLE (verified) |
| Food Gatherers | MI | custom/JS map (undetermined) |  |  |  | needs-headless |
| Forgotten Harvest | MI | Vivery/AccessFood |  |  | boiler | BLOCKED (Vivery) |
| Gleaners Community Food Bank of Southeastern Michigan | MI | Vivery/AccessFood |  |  |  | BLOCKED (Vivery) |
| Greater Lansing Food Bank | MI | custom/JS map (undetermined) |  |  |  | needs-headless |
| South Michigan Food Bank | MI | static HTML list |  |  |  | SCRAPEABLE (html) |
| Channel One Regional Food Bank | MN | WP Go Maps (wpgmza) | www.helpingfeedpeople.org/wp-json/wpgmza/v1/markers | 89 |  | SCRAPEABLE (verified) |
| North Country Food Bank, Inc. | MN | inline-JSON map |  |  |  | SCRAPEABLE (inline-json) |
| Second Harvest Heartland | MN | custom/JS map (undetermined) |  |  |  | needs-headless |
| Second Harvest Northland | MN | Vivery/AccessFood |  |  |  | BLOCKED (Vivery) |
| Harvesters - The Community Food Network | MO | custom/JS map (undetermined) |  |  |  | needs-headless |
| Ozarks Food Harvest | MO | inline-JSON map |  |  |  | SCRAPEABLE (inline-json) |
| Second Harvest Community Food Bank | MO | custom/JS map (undetermined) |  |  |  | needs-headless |
| Southeast Missouri Food Bank | MO | custom/JS map (undetermined) |  |  |  | needs-headless |
| St. Louis Area Foodbank | MO | WP Store Locator | stlfoodbank.org/wp-admin/admin-ajax.php?action=store_search&autolo… | 50* |  | SCRAPEABLE (verified) |
| The Food Bank for Central & Northeast Missouri | MO | custom/JS map (undetermined) |  |  |  | needs-headless |
| Mississippi Food Network | MS | Vivery/AccessFood |  |  |  | BLOCKED (Vivery) |
| Montana Food Bank Network | MT | static HTML list |  |  |  | SCRAPEABLE (html) |
| Food Bank of Central & Eastern North Carolina | NC | static HTML list |  |  |  | SCRAPEABLE (html) |
| Food Bank of the Albemarle | NC | WP Store Locator |  |  |  | scrapeable (likely) |
| Inter-Faith Food Shuttle | NC | Google My Maps | www.google.com/maps/d/kml?mid=1ufqSw9bSrfF9HltumRDL6biGzmvgWFc&for… | 27 |  | SCRAPEABLE (verified) |
| MANNA FoodBank | NC | Vivery/AccessFood |  |  |  | BLOCKED (Vivery) |
| Second Harvest Food Bank of Metrolina | NC | custom/JS map (undetermined) |  |  |  | needs-headless |
| Second Harvest Food Bank of Northwest North Carolina | NC | ArcGIS FeatureServer |  |  |  | scrapeable (likely) |
| Second Harvest Food Bank of Southeast North Carolina | NC | Store Locator Plus | hungercantwait.org/wp-admin/admin-ajax.php?action=csl_ajax_onload&… | 50* |  | SCRAPEABLE (verified) |
| Great Plains Food Bank | ND | WP Go Maps (wpgmza) | greatplainsfoodbank.org/wp-json/wpgmza/v1/markers | 2 |  | SCRAPEABLE (verified) |
| Food Bank for the Heartland | NE | Storepoint | api.storepoint.co/v1/161e1dcd91b7b8/locations?rq | 180 |  | SCRAPEABLE (verified) |
| Food Bank of Lincoln | NE | Google My Maps | www.google.com/maps/d/kml?mid=1-fJ6qDSkRyYFuINZPbOev_Y6HaLN29id&fo… | 47 |  | SCRAPEABLE (verified) |
| New Hampshire Food Bank | NH | Vivery/AccessFood |  |  |  | BLOCKED (Vivery) |
| Community Foodbank of New Jersey | NJ | Vivery/AccessFood |  |  |  | BLOCKED (Vivery) |
| Food Bank of South Jersey | NJ | Agile Store Locator | foodbanksj.org/wp-admin/admin-ajax.php?action=asl_load_stores&load… | 165 |  | SCRAPEABLE (verified) |
| Fulfill | NJ | Agile Store Locator | fulfillnj.org/wp-admin/admin-ajax.php?action=asl_load_stores&load_… | 127 |  | SCRAPEABLE (verified) |
| Roadrunner Food Bank | NM | Vivery/AccessFood |  |  | boiler | BLOCKED (Vivery) |
| Food Bank of Northern Nevada | NV | custom/JS map (undetermined) |  |  |  | needs-headless |
| Three Square Food Bank | NV | custom/JS map (undetermined) |  |  |  | needs-headless |
| City Harvest | NY | custom/JS map (undetermined) |  |  |  | needs-headless |
| FeedMore Western New York, Inc. | NY | Store Locator Plus | www.feedmorewny.org/wp-admin/admin-ajax.php?action=csl_ajax_onload… | 25* |  | SCRAPEABLE (verified) |
| Feeding Westchester | NY | WP Store Locator |  |  |  | scrapeable (likely) |
| Food Bank For New York City | NY | custom/JS map (undetermined) |  |  |  | needs-headless |
| Food Bank of Central New York | NY | Vivery/AccessFood |  |  |  | BLOCKED (Vivery) |
| Food Bank of the Southern Tier | NY | Vivery/AccessFood |  |  |  | BLOCKED (Vivery) |
| Foodlink, Inc. | NY | Vivery/AccessFood |  |  | boiler | BLOCKED (Vivery) |
| Island Harvest | NY | StoreRocket |  |  |  | scrapeable (likely) |
| Long Island Cares, Inc. | NY | custom/JS map (undetermined) |  |  |  | needs-headless |
| Regional Food Bank of Northeastern New York | NY | WP Store Locator | regionalfoodbank.net/wp-admin/admin-ajax.php?action=store_search&a… | 25* | boiler | SCRAPEABLE (verified) |
| Akron-Canton Regional Foodbank | OH | custom/JS map (undetermined) |  |  |  | needs-headless |
| Freestore Foodbank | OH | Google My Maps | www.google.com/maps/d/kml?mid=14JPRi0SFtdGN_pOP6c7w4vJpvXlvl0I&for… | 264 | **STRONG** | SCRAPEABLE (verified) |
| Greater Cleveland Food Bank | OH | inline-JSON map |  |  |  | SCRAPEABLE (inline-json) |
| Mid-Ohio Food Collective | OH | static HTML list |  |  |  | SCRAPEABLE (html) |
| SE Ohio Foodbank | OH | custom/JS map (undetermined) |  |  |  | needs-headless |
| Second Harvest Food Bank of Clark, Champaign & Logan Counties | OH | custom/JS map (undetermined) |  |  |  | needs-headless |
| Second Harvest Food Bank of North Central Ohio | OH | custom/JS map (undetermined) |  |  |  | needs-headless |
| Second Harvest Food Bank of the Mahoning Valley | OH | custom/JS map (undetermined) |  |  |  | needs-headless |
| Shared Harvest Foodbank | OH | custom/JS map (undetermined) |  |  |  | needs-headless |
| The Foodbank, Inc. | OH | static HTML list |  |  |  | SCRAPEABLE (html) |
| Toledo Northwestern Ohio Food Bank | OH | Storepoint | api.storepoint.co/v1/1662a5ad8a1488/locations?rq | 132 |  | SCRAPEABLE (verified) |
| West Ohio Food Bank | OH | custom/JS map (undetermined) |  |  |  | needs-headless |
| Food Bank of Eastern Oklahoma | OK | WP Go Maps (wpgmza) | okfoodbank.org/wp-json/wpgmza/v1/markers | 274 |  | SCRAPEABLE (verified) |
| Regional Food Bank of Oklahoma | OK | Vivery/AccessFood |  |  |  | BLOCKED (Vivery) |
| Oregon Food Bank | OR | static HTML list |  |  |  | SCRAPEABLE (html) |
| CEO Weinberg Northeast Regional Foodbank | PA | custom/JS map (undetermined) |  |  |  | needs-headless |
| Central Pennsylvania Food Bank | PA | Vivery/AccessFood |  |  |  | BLOCKED (Vivery) |
| Greater Pittsburgh Community Food Bank | PA | custom/JS map (undetermined) |  |  |  | needs-headless |
| Helping Harvest | PA | custom/JS map (undetermined) |  |  |  | needs-headless |
| Mercer County Food Bank | PA | Vivery/AccessFood |  |  |  | BLOCKED (Vivery) |
| Philabundance | PA | WP Store Locator | www.philabundance.org/wp-admin/admin-ajax.php?action=store_search&… | 10* | boiler | SCRAPEABLE (verified) |
| Second Harvest Food Bank of Lehigh Valley and NE Pennsylvania | PA | WP Store Locator | shfblv.org/wp-admin/admin-ajax.php?action=store_search&autoload=1 | 20* |  | SCRAPEABLE (verified) |
| Second Harvest Food Bank of Northwest Pennsylvania | PA | custom/JS map (undetermined) |  |  |  | needs-headless |
| Westmoreland Food Bank | PA | Vivery/AccessFood |  |  |  | BLOCKED (Vivery) |
| Banco de Alimentos de Puerto Rico | PR | custom/JS map (undetermined) |  |  |  | needs-headless |
| Rhode Island Community Food Bank | RI | WP Store Locator | rifoodbank.org/wp-admin/admin-ajax.php?action=store_search&autoloa… | 50* |  | SCRAPEABLE (verified) |
| Harvest Hope Food Bank | SC | ArcGIS FeatureServer | services1.arcgis.com/x5wCko8UnSi4h0CB/arcgis/rest/services/_Food_P… | 89 |  | SCRAPEABLE (verified) |
| Lowcountry Food Bank | SC | Agile Store Locator | lowcountryfoodbank.org/wp-admin/admin-ajax.php?action=asl_load_sto… | 208 |  | SCRAPEABLE (verified) |
| Feeding South Dakota | SD | custom/JS map (undetermined) |  |  | boiler | needs-headless |
| Chattanooga Area Food Bank | TN | Vivery/AccessFood |  |  |  | BLOCKED (Vivery) |
| Mid-South Food Bank | TN | custom/JS map (undetermined) |  |  |  | needs-headless |
| Second Harvest Food Bank Of Middle Tennessee Inc | TN | StoreRocket |  |  |  | scrapeable (likely) |
| Second Harvest Food Bank of East Tennessee | TN | Google My Maps | www.google.com/maps/d/kml?mid=16ei4cVPP4mTcCaEocPz3eV4Pd3qm5ZA&for… | 184 |  | SCRAPEABLE (verified) |
| Second Harvest Food Bank of Northeast Tennessee | TN | Vivery/AccessFood |  |  |  | BLOCKED (Vivery) |
| Central Texas Food Bank | TX | Vivery/AccessFood |  |  |  | BLOCKED (Vivery) |
| Coastal Bend Food Bank | TX | WP Store Locator | coastalbendfoodbank.org/wp-admin/admin-ajax.php?action=store_searc… | 50* |  | SCRAPEABLE (verified) |
| East Texas Food Bank | TX | Vivery/AccessFood |  |  |  | BLOCKED (Vivery) |
| El Pasoans Fighting Hunger | TX | Link2Feed (intake) |  |  |  | rejected (intake sw) |
| Food Bank of West Central Texas | TX | Google My Maps | www.google.com/maps/d/kml?mid=15jt8EPmUrPHFQsKt6ESIDVGXgz3fqVs&for… | 66 | consent | SCRAPEABLE (verified) |
| Food Bank of the Golden Crescent | TX | Vivery/AccessFood |  |  |  | BLOCKED (Vivery) |
| Food Bank of the Rio Grande Valley | TX | custom/JS map (undetermined) |  |  |  | needs-headless |
| High Plains Food Bank | TX | Vivery/AccessFood |  |  |  | BLOCKED (Vivery) |
| Houston Food Bank | TX | custom/JS map (undetermined) |  |  |  | needs-headless |
| North Texas Food Bank | TX | Vivery/AccessFood |  |  |  | BLOCKED (Vivery) |
| San Antonio Food Bank | TX | custom/JS map (undetermined) |  |  |  | needs-headless |
| South Plains Food Bank | TX | custom/JS map (undetermined) |  |  |  | needs-headless |
| South Texas Food Bank | TX | Vivery/AccessFood |  |  | boiler | BLOCKED (Vivery) |
| Southeast Texas Food Bank | TX | custom/JS map (undetermined) |  |  |  | needs-headless |
| Tarrant Area Food Bank | TX | Vivery/AccessFood |  |  | boiler | BLOCKED (Vivery) |
| West Texas Food Bank | TX | custom/JS map (undetermined) |  |  |  | needs-headless |
| Wichita Falls Area Food Bank | TX | Vivery/AccessFood |  |  |  | BLOCKED (Vivery) |
| Utah Food Bank | UT | Vivery/AccessFood |  |  |  | BLOCKED (Vivery) |
| Blue Ridge Area Food Bank | VA | static HTML list |  |  |  | SCRAPEABLE (html) |
| Feed More | VA | AgencyURL dead |  |  |  | AgencyURL dead |
| Feeding Southwest Virginia | VA | WP Go Maps (wpgmza) | feedingswva.org/wp-json/wpgmza/v1/markers | 3 |  | SCRAPEABLE (verified) |
| Foodbank of Southeastern Virginia and the Eastern Shore | VA | WP Store Locator |  |  |  | scrapeable (likely) |
| Fredericksburg Regional Food Bank | VA | Vivery/AccessFood |  |  |  | BLOCKED (Vivery) |
| Virginia Peninsula Foodbank | VA | Vivery/AccessFood |  |  |  | BLOCKED (Vivery) |
| Vermont Foodbank | VT | Vivery/AccessFood |  |  |  | BLOCKED (Vivery) |
| Food Lifeline | WA | Vivery/AccessFood |  |  |  | BLOCKED (Vivery) |
| Second Harvest Inland Northwest | WA | custom/JS map (undetermined) |  |  |  | needs-headless |
| Feeding America Eastern Wisconsin | WI | WP Go Maps (wpgmza) | feedingamericawi.org/wp-json/wpgmza/v1/markers | 348 |  | SCRAPEABLE (verified) |
| Second Harvest Foodbank of Southern Wisconsin | WI | WP Go Maps (wpgmza) | www.secondharvestsw.org/wp-json/wpgmza/v1/markers | 4 | boiler | SCRAPEABLE (verified) |
| Facing Hunger Foodbank | WV | Vivery/AccessFood |  |  |  | BLOCKED (Vivery) |
| Mountaineer Food Bank | WV | static HTML list |  |  |  | SCRAPEABLE (html) |

_Survey run 2026-07-19/20. Probe cache and per-bank classification retained in the run scratchpad; not committed (raw-source rule, DATA-RIGHTS)._
