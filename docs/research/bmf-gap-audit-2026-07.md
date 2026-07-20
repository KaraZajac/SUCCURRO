# BMF gap audit — IRS Exempt Organizations Business Master File vs SUCCURRO

*2026-07 · analysis only · sources cached in `sources/irs/eo{1..4}.csv` (1,983,563 rows, July 2026 pull)*

The IRS EO BMF lists every tax-exempt org with a mailing address and (for ~71% of rows) an
NTEE activity code. We map service-relevant NTEE classes onto SUCCURRO root categories and ask:
**where do lots of registered nonprofits of a class exist that SUCCURRO covers not at all?**
This is a discovery heatmap for source-hunting — not ground truth (see caveats).

## NTEE -> root category mapping

| NTEE | Root | Notes |
|---|---|---|
| E* | health | hospitals, clinics, health orgs |
| F20-F22, F50-F54 | recovery | substance abuse prevention/treatment; addictive disorders (smoking, eating, gambling) |
| F40, F42 | crisis | hotlines & crisis intervention; rape victim services |
| F* (rest) | mental-health | treatment, counseling, associations |
| K30-K36 | food | food programs, banks, pantries, congregate meals, soup kitchens, meals on wheels |
| L* | housing | housing development, shelters, homeless services |
| P30-P33, P40-P46 (not P43) | family-youth | children & youth services, family services |
| P43 | crisis | family violence shelters & services |
| P51, P60 | financial | financial counseling; emergency assistance (food/clothing/cash) |
| P81 | seniors | senior centers & services |
| W30 | veterans | military & veterans organizations |
| I80-I89 | legal | legal services, public interest law |

Left unmapped on purpose: P20 (multipurpose human services — too generic), K other than K3x,
and everything outside these letters. 172,467 BMF orgs land in a mapped class.

## Method

1. **Coverage** — every record in `data/sites/`, `data/meetings/`, and `data/orgs/` (orgs joined
   via `place` geoid) contributes its categories' *root* tokens (taxonomy parent-walk, same as
   `site/src/lib/data.js` `categoryCounts`) to its `(state, place)`; 16,477 served places.
2. **Match** — BMF `CITY`/`STATE` resolved through `pipeline.emit.Places().resolve` (case-folded,
   Saint/St aliases). 87.4% of mapped-class orgs resolve to a registry place; the rest are
   misspellings, unincorporated mail towns, or APO/odd addresses and are excluded from tables.
3. **Gap** — a resolved BMF org is *uncovered* when its place has zero SUCCURRO records whose
   root matches its class. Per class we rank places by uncovered-org count (top 50 computed;
   top 8 shown).

### Caveats — read before acting

- BMF rows are **mailing addresses**: HQ/registered-agent/PO-box clusters masquerade as service
  locations (e.g. Oceanport NJ's 41 "health" orgs are one hospital system's corporate filings).
- The file includes **shells, dormant and defunct orgs, foundations, and group-ruling posts**
  (W30 counts every VFW/Legion post charter, not a staffed service site).
- NTEE codes are coarse, often self-assigned or imputed; 29% of rows have none.
- Small/one-place states distort percentages; weak-state lists require >=50 matched orgs.
- Treat every number as "worth a look", never as "orgs we're missing".

## Headline coverage

Across all mapped classes: **87.4%** of orgs resolve to a registry place;
of those, **95.5%** sit in a place SUCCURRO serves at all, but only
**68.5%** sit in a place covered *for their own category*.

| Category | BMF orgs | resolved | in served place | in place covered for class | weakest states (covered %, n>=50) |
|---|---|---|---|---|---|
| health | 46,717 | 87% | 95.9% | **73.4%** | NJ 42%, MN 43%, IA 44%, NH 48%, UT 50% |
| housing | 31,668 | 88% | 97.4% | **66.1%** | ID 16%, DE 19%, HI 26%, UT 29%, AK 37% |
| family-youth | 24,924 | 87% | 95.9% | **82.4%** | NH 41%, ND 51%, VT 64%, NJ 66%, UT 68% |
| mental-health | 18,781 | 87% | 96.2% | **79.0%** | SD 63%, NJ 65%, MN 65%, MS 66%, ME 66% |
| veterans | 14,392 | 85% | 90.6% | **35.6%** | NJ 10%, NH 16%, ME 18%, IN 19%, IA 21% |
| food | 12,065 | 88% | 92.7% | **79.9%** | ND 32%, SD 47%, NJ 53%, MN 59%, IL 62% |
| recovery | 8,666 | 88% | 96.8% | **90.4%** | MS 66%, UT 75%, AL 77%, NJ 83%, GA 84% |
| financial | 7,411 | 87% | 95.4% | **46.2%** | UT 16%, NY 23%, NJ 28%, IL 29%, MD 31% |
| seniors | 3,674 | 88% | 91.4% | **8.0%** | MN 0%, WI 0%, WA 0%, AZ 0%, MA 1% |
| crisis | 2,186 | 89% | 97.0% | **20.8%** | MI 1%, NC 2%, GA 12%, TX 20%, CA 21% |
| legal | 1,983 | 89% | 98.6% | **38.5%** | FL 30%, WA 40%, CA 43%, PA 53%, TX 53% |

## Top gap cities per category

Places with **zero** SUCCURRO records of the class, ranked by BMF org count in that class.

### health

| State | City | BMF orgs |
|---|---|---|
| NJ | Oceanport | 41 |
| MD | Bowie | 40 |
| TN | Brentwood | 37 |
| OH | Independence | 34 |
| MD | Annapolis | 32 |
| MI | Livonia | 31 |

### housing

| State | City | BMF orgs |
|---|---|---|
| CA | Oakland | 95 |
| DE | Wilmington | 79 |
| TX | Spring | 77 |
| TX | Katy | 72 |
| MI | Warren | 66 |
| CA | Irvine | 65 |

### family-youth

| State | City | BMF orgs |
|---|---|---|
| GA | Lithonia | 25 |
| GA | McDonough | 24 |
| TX | Frisco | 23 |
| TX | Cedar Hill | 21 |
| GA | Fairburn | 16 |
| GA | Stockbridge | 16 |

### mental-health

| State | City | BMF orgs |
|---|---|---|
| GA | McDonough | 16 |
| CO | Centennial | 12 |
| TX | Missouri City | 12 |
| CA | Fontana | 11 |
| PA | Villanova | 10 |
| TX | Grand Prairie | 10 |

### veterans

| State | City | BMF orgs |
|---|---|---|
| VA | Springfield | 47 |
| VA | Arlington | 23 |
| TX | Spring | 17 |
| NV | Nellis AFB | 16 |
| CA | Beale AFB | 13 |
| IL | Scott AFB | 11 |

### food

| State | City | BMF orgs |
|---|---|---|
| TX | Frisco | 7 |
| WA | Sammamish | 6 |
| MA | Pittsfield | 5 |
| NY | New Rochelle | 5 |
| IN | Noblesville | 5 |
| MN | Eden Prairie | 5 |

### recovery

| State | City | BMF orgs |
|---|---|---|
| OH | Euclid | 4 |
| NC | Denver | 3 |
| TN | Gainesboro | 3 |
| UT | Cedar Hills | 3 |
| GA | Brooklet | 3 |
| GA | College Park | 3 |

### financial

| State | City | BMF orgs |
|---|---|---|
| NY | New York | 47 |
| GA | Lawrenceville | 21 |
| GA | Douglasville | 16 |
| NJ | Lakewood | 15 |
| GA | Marietta | 15 |
| AZ | Scottsdale | 14 |

### seniors

| State | City | BMF orgs |
|---|---|---|
| PA | Philadelphia | 21 |
| IL | Chicago | 14 |
| AZ | Phoenix | 12 |
| MD | Baltimore | 11 |
| TX | Houston | 11 |
| MO | St. Louis | 11 |

### crisis

| State | City | BMF orgs |
|---|---|---|
| CA | Los Angeles | 15 |
| NV | Las Vegas | 11 |
| AZ | Phoenix | 10 |
| TX | Dallas | 10 |
| MI | Detroit | 8 |
| NC | Charlotte | 6 |

### legal

| State | City | BMF orgs |
|---|---|---|
| WI | Madison | 16 |
| WI | Milwaukee | 13 |
| MO | Kansas City | 12 |
| PA | Harrisburg | 11 |
| OK | Oklahoma City | 11 |
| CA | San Jose | 11 |

## Where to hunt next (prioritized)

1. **seniors (8% covered)** — a near-total blind spot: no senior-services source exists in the
   pipeline, so every major city (Philadelphia, Chicago, Phoenix, Baltimore...) is a gap. One
   source fixes most of it: ACL's Eldercare Locator directory of Area Agencies on Aging and
   senior centers.
2. **crisis (21%)** — the class is mostly P43 domestic-violence shelters; NNEDV/NYSCADV give
   coalitions, not local programs. Hunt state DV-coalition member directories (MI 1% and NC 2%
   covered — start there) and RAINN's sexual-assault center list for F42.
3. **veterans (36%)** — current coverage is VA facilities + Team RWB; the W30 mass is VFW/Legion/
   DAV posts and base-town orgs. County Veteran Service Officer directories are the serviceable
   layer; treat the AFB rows and Springfield VA (national HQ mail drop) as mailing artifacts.
4. **financial (46%)** — P60 emergency-assistance orgs cluster in suburban metro Atlanta and NYC.
   NFCC member agencies (financial counseling) and 211-style emergency-assistance listings; UT,
   NY, NJ weakest.
5. **legal (39%)** — only LSC grantees today. LawHelp.org / state-bar legal aid directories;
   Wisconsin (Madison + Milwaukee at the top of the gap table) is the loudest single-state miss.
6. **housing (66%) & health (73%)** — biggest absolute uncovered counts. An Oakland CA housing
   gap despite the HUD source suggests whole-city misses worth spot-checking; ID/DE/HI trail on
   housing, NJ/MN/IA on health.
7. **Cross-cutting geography** — NJ and MN rank among the five weakest states in most classes;
   suburban Atlanta (McDonough, Lithonia, Lawrenceville, Stockbridge) recurs across family-youth,
   mental-health, and financial. A statewide NJ/MN sweep and a metro-Atlanta suburb sweep would
   each close gaps in several categories at once.
