# SUCCURRO data model

Everything under `data/` is YAML, one file per record, sharded by state (USPS
two-letter, lowercase) and place slug. Conventions shared with JUDGMENT/TOCSIN/AUSPEX:

- Dates are plain quoted strings `YYYY-MM-DD` — never YAML timestamp objects.
- **Absent means absent** — omit fields the source didn't provide; never write `null`.
  (Exception: a source record may carry `url: null` *with an explanatory note* when no
  live URL exists.)
- Enumerated fields are kebab-case tokens validated against `data/taxonomy/`.
- Foreign keys are id strings; the validator errors on dangling references.
- Slugs are stable forever. Corrections add `aliases:`; ids never change.
- Small structured values use YAML flow style (`geo: {lat: 33.7743, lng: -117.9380}`).

## Entities

### Place — `data/places/<state>.yaml` (one file per state, list of records)

The geo backbone: every incorporated place and census-designated place (plus county
subdivisions where they are the operative unit, e.g. New England towns), derived from
the Census Bureau gazetteer. Authoritative upstream id = Census `GEOID`.

```yaml
- id: "0630000"            # Census GEOID (string — leading zeros matter)
  slug: garden-grove       # url-safe, unique within state
  name: Garden Grove
  state: ca
  kind: city               # city | town | village | borough | cdp | township
  county: Orange
  geo: {lat: 33.7787, lng: -117.9601}
```

### Organization — `data/orgs/<state>/<slug>.yaml`

The canonical entity: a NAMI affiliate, an AA intergroup, a food bank, a shelter
operator, an LGBTQ+ center. Statewide/national orgs live under the state of their HQ;
national umbrella orgs (AA GSO, Feeding America) use state `us`.

```yaml
id: ca/nami-orange-county          # <state>/<slug>
name: NAMI Orange County
categories: [mental-health, peer-support]   # tokens from taxonomy/services.yaml
parent_org: us/nami                # optional FK — affiliate/chapter hierarchy
website: https://namioc.org
phone: "714-544-8488"              # phones are strings, E.164 or US 10-digit dashed
email: info@namioc.org
service_area: {kind: county, name: Orange, state: ca}   # county | place | state | national
languages: [en, es, vi]            # ISO 639-1
sources: [nami/affiliate-directory-2026]
verified: {on: "2026-07-19", method: scrape}   # method: api | scrape | human
```

### Site — `data/sites/<state>/<place>/<slug>.yaml`

A physical location where services are delivered: a pantry address, a shelter, a VA
clinic, a drop-in center. Always belongs to an org.

```yaml
id: ca/garden-grove/oc-food-bank-distribution-center
org: ca/oc-food-bank                   # FK
name: OC Food Bank Distribution Center
categories: [food-pantry]
address: {street: 11870 Monarch St, city: Garden Grove, state: ca, zip: "92841"}
place: "0630000"                       # FK → place GEOID
geo: {lat: 33.7743, lng: -117.9380}
phone: "714-897-6670"
hours:                                 # day tokens mon..sun; 24h HH:MM strings
  - {days: [mon, tue, wed, thu, fri], open: "08:00", close: "16:30"}
eligibility: Open to all OC residents; photo ID requested but not required.
cost: free                             # free | sliding-scale | insurance | varies
accessibility: [wheelchair]
sources: [oc-food-bank/locations-page-2026]
verified: {on: "2026-07-19", method: scrape}
```

### Meeting — `data/meetings/<state>/<place>/<slug>.yaml`

A recurring group meeting: an AA/NA/Al-Anon meeting, a NAMI support group, a grief
group. May reference a site or carry its own venue; online-only meetings set
`format: online` and omit place/venue.

```yaml
id: ca/garden-grove/serenity-at-seven
name: Serenity at Seven
program: aa                        # aa | na | al-anon | alateen | smart | nami | ...
categories: [recovery-meeting]
org: ca/oc-aa-central-office       # optional FK
schedule:
  - {day: tue, time: "19:00", duration_min: 60}
format: in-person                  # in-person | online | hybrid
types: [open, discussion]          # program-specific tokens (TSML-derived for 12-step)
venue: {name: St Anselm Church, street: 13091 Galway St, city: Garden Grove, state: ca, zip: "92844"}
place: "0630000"
geo: {lat: 33.7621, lng: -117.9445}
languages: [en]
sources: [oc-aa/meeting-guide-feed-2026]
verified: {on: "2026-07-19", method: api}
```

### Source — `data/sources/<publisher>/<slug>.yaml`

First-class provenance records, AUSPEX-style. Every org/site/meeting cites at least
one. Copyrighted page bodies are never committed — only URL, archive URL, and hash;
raw snapshots live in gitignored `sources/`.

```yaml
id: nami/affiliate-directory-2026
kind: directory                    # directory | api-feed | dataset | org-website | registry
publisher: NAMI
title: NAMI Affiliate Directory
url: https://www.nami.org/findsupport
archive_url: https://web.archive.org/web/2026.../...
retrieved_on: "2026-07-19"
tier: primary                      # primary (the org itself / official feed)
                                   # secondary (aggregator, e.g. 211)
                                   # tertiary (news, third-party lists)
```

### Taxonomy — `data/taxonomy/services.yaml`

Single file, flat list, hierarchy via `parent`. Tokens referenced by `categories:`
everywhere. Never delete a token; deprecate with `superseded_by`.

## Identity, dedup, precedence

- **Authoritative upstream ids are kept** whenever they exist (Census GEOID, SAMHSA
  facility id, VA facility id, BMLT meeting id) in an `external_ids:` map, e.g.
  `external_ids: {samhsa: "CA123456", bmlt: "1234"}`. Dedup across sources joins on
  these first, then on normalized (name, address) match.
- **Layered precedence** (JUDGMENT pattern): a record built from a primary source
  (the org's own feed/site or an official government dataset) supersedes one built
  from an aggregator. Provisional records carry `provisional: true` until verified.
- **Newest wins** within a source (TOCSIN pattern): re-pulls replace by upstream id.

## Freshness

`verified: {on, method}` is required on org/site/meeting records. The validator warns
(soft finding) when `on` is older than 180 days for sites/orgs, 90 days for meetings,
and errors on missing stamps. Staleness thresholds live in `pipeline/validate.py`.
