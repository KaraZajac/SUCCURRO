# SUCCURRO

A curated, source-anchored, hyper-local dataset of help and support services across the
United States — mutual-aid meetings (AA, NA, Al-Anon, SMART), NAMI affiliates and peer
support, shelters and housing assistance, food banks and pantries, veteran services,
LGBTQ+ centers, crisis lines, free clinics, legal aid — resolvable down to the city and
town level, plus a static Astro site that makes it searchable by location and need.

*Succurro* (Latin): to run to the aid of, to help.

## Design

Same family skeleton as [JUDGMENT](https://github.com/KaraZajac/JUDGMENT),
[TOCSIN](https://github.com/KaraZajac/TOCSIN), and
[AUSPEX](https://github.com/KaraZajac/AUSPEX):

- **`sources/`** — raw downloads and scrape caches. Gitignored, regenerable, never
  redistributed.
- **`data/`** — the committed dataset. One YAML file per record, sharded by state and
  city. Deterministic: same sources + same curated inputs ⇒ identical YAML. Never
  hand-edit generated records; fix the pipeline or the curated inputs and rebuild.
- **`pipeline/`** — Python (stdlib + PyYAML) module CLIs: `python3 -m pipeline.<name>`.
  One module per source, each with on-disk caching, polite throttling, and loud payload
  validation.
- **`site/`** — static Astro site reading `../data` at build time. Search via Pagefind
  plus a build-time JSON index for location/category faceting.

Core rules inherited from the family:

- **No source, no ship.** Every record carries a `sources:` list pointing at
  first-class source records (URL, archive URL, retrieval date).
- **Freshness is a first-class field.** Every operational record carries a `verified:`
  stamp; the validator flags staleness. A wrong phone number in a crisis directory is a
  safety issue, not a cosmetic one.
- **Stable slugs forever.** Corrections add aliases; ids never change.
- **Absent means absent.** Omit fields the source didn't provide; never write `null`.
- Dates are plain strings `YYYY-MM-DD`. Enumerated fields are kebab-case tokens
  checked against `data/taxonomy/`.

## Layout

    data/
      meta.yaml                     dataset version, counts, coverage
      taxonomy/services.yaml        controlled service-category taxonomy
      places/<state>.yaml           place registry: every city/town, Census-derived
      orgs/<state>/<slug>.yaml      organizations
      sites/<state>/<place>/<slug>.yaml    physical locations
      meetings/<state>/<place>/<slug>.yaml recurring meetings/groups
      sources/<publisher>/<slug>.yaml      first-class source records
    docs/
      data-model.md                 the schema reference
      sources.md                    source registry (status: in-use / planned / tested)
      roadmap.md                    phased build plan
    schemas/succurro.schema.json    JSON Schema conformance gate
    pipeline/                       ETL modules

## Running

    make help          # list targets
    make places        # build the national place registry (Census gazetteer)
    make verify        # validation gate (schema conformance + referential integrity)
    make install-hooks # pre-commit gate on data/ changes

## License

Code is MIT (`LICENSE`). Dataset rights are layered per source — see `DATA-RIGHTS.md`.
