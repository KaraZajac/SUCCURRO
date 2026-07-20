# Support-group directory sweep — round 2 (2026-07-20)

36 sources investigated, 19 live-verified endpoints. Key findings; build
order at bottom. (Condensed from the discovery agent's full report.)

## Verified candidates

| Source | What | Endpoint | Count | Notes |
|---|---|---|---|---|
| La Leche League USA | breastfeeding support groups | `lllusa.org/wp-json/wpgmza/v1/markers?filter={}` (one GET) | 396 | best effort/quality of round |
| Nar-Anon | addiction-family groups | Knack API `api.knack.com/v1/scenes/scene_5/views/view_7/records` (X-Knack-Application-Id 54dd0787f294e1891969b4db, key "knack") | 1,241 world | archive-early |
| Gamblers Anonymous | GA meetings | `event_listing-sitemap{,2,3}.xml` → detail pages w/ schema.org Event JSON-LD | 2,996 US | biggest of round |
| Adult Children of Alcoholics | ACA meetings | `POST /wp-json/wsom/v1/meeting-search/` (nonce; param combo unsolved — headless capture) + enumerable `meeting-popup-details` SIDs | 2,991 in DB | strong probe |
| Overeaters Anonymous | OA meetings | `POST oa.org/wp-json/oa-meetings/v1/meetings_search` `{"paged":N,...}` | 927 (verify vs ~6k claim) | HTML-in-JSON |
| The Arc | disability chapters | `thearc.org/chapter-sitemap.xml` → 578 pages | ~578 | |
| AFSP | suicide-prevention chapters | `afsp.org/sitemap-0.xml` /chapter/ URLs (~75 real) | ~75 | zip API was 503 (Heroku down) |
| AFSP support groups | suicide-loss groups | `POST afsp-support-groups-700295b25974.herokuapp.com/support-groups-find` {"zip","radius","type","country"} | 100s | 503 at test — retest |
| Alzheimer's Assoc. | chapters | `POST alz.org/api/chapter/search` {"zip"} | ~75 | |
| Debtors Anonymous | DA meetings | `/meeting-search-f2f/?cn=USA` single table | 138 US + virtual | |
| Gam-Anon | GA-family meetings | one Joomla page `/meeting-directory/us-meetings` | ~78 | |
| TransFamilies | trans-family online groups | `/wp-json/tribe/events/v1/events` | 67 | complements PFLAG |
| Autism Society | affiliates | inline list on `/contact-us/` | ~72 | |
| Glisten (ex-GLSEN) | chapters | `glisten.org/our-chapters/` | 15 | |
| Bereaved Parents USA | grief chapters | one page | ~50 | |
| POMC | homicide-loss chapters | `pomc.org/chapters/` | 32 | |
| Team RWB | veteran chapters | inline on find-your-chapter | 201 (city-level) | |
| NYSCADV | NY DV programs | server-rendered county directory | ~100 | template for 50-state coalition sweep (est. 15–25 scrapeable states) |
| SAA | SA meetings | Drupal views pagination, full addresses | ~700 | **policy decision needed before building** (sensitivity) |

## Probes / blocked

- MS Society self-help groups: 208 slugs extractable from SPA manifest; content API needs headless capture.
- Epilepsy Foundation: full bot wall (403) — headless.
- PSI (postpartum): app-mediated; static-seed helpline at minimum.
- Soaring Spirits, TAPS care groups: JS event systems, small — headless later.
- CPEDV (CA DV coalition): JS map, no XHR found.
- **GriefShare / Church Initiative: explicit anti-automation ToS — permission-first** (one email could unlock DivorceCare siblings too).
- CRF/Carelike (Alz community finder): commercial DB — rejected.
- MOPS/MomCo: signup-gated — rejected.
- AGID correction: state profiles are program statistics, not AAA directories — Eldercare Locator (ODbL) remains the AAA route.

## Negative finding

None of the 12-step-adjacent fellowships runs TSML — every meeting list is a
bespoke stack. The TSML registry remains AA-specific.

## Build order

Tier 1 (one-request JSON): LLL USA, Nar-Anon, Alz chapters, TransFamilies.
Tier 2 (enumerable): GA sitemap, The Arc, AFSP chapters, OA, DA.
Tier 3 (single-page batch): BPUSA, POMC, Gam-Anon, Autism Society, Glisten,
Team RWB, NYSCADV.
Probe queue: AFSP groups API (retest), ACA (headless), MS Society, Epilepsy.
Held for policy: SAA. Held for permission: GriefShare.
