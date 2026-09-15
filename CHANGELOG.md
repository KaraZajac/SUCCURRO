# Changelog

Counts are from `stats.json` in each release bundle. Dataset is CC BY-NC 4.0,
code MIT; see DATA-RIGHTS.md.

## v1.1 — 2026-09-15

Data through 2026-09-15. **12,950** organizations · **136,526** sites ·
**74,790** meetings · **32,307** places · **251** sources.

### Corrections

- **A private phone number has been removed** from the Residencial Enrique
  Catoni meal-site listing (`pr/vega-baja/residencial-enrique-catoni`). It was
  published upstream by USDA FNS in the `Site_Phone` field of master record
  `Cycle 07_PR_SFSP_0198` and copied here verbatim; its owner asked for its
  removal. A correction has been requested from USDA FNS. See
  `docs/takedowns.md`.
- **Removal requests now survive a refresh.** Deleting a record was never
  enough: each module re-emits from its upstream pull, so the next refresh
  restored whatever the source still served — as in fact happened on
  2026-09-05, ten days before this release. Suppressed contact values now live
  in `pipeline/curated/suppressed.yaml` as one-way hashes, are applied at every
  write, and are enforced by the validation gate.

### Recovered coverage

- **7,174 AA meetings are back.** Eight intergroup TSML feeds began returning
  403/401 to the project's user agent; `tsml.py` logged a warning and carried
  on, and because the module owns the whole `aa/` prefix, every meeting those
  feeds owned was deleted. AA listings for Philadelphia, Atlanta, Kansas City,
  Portland, the East Bay, South Dakota Area 63 and Raleigh were missing from
  the site between the 2026-08-05 refresh and this release. They are restored.
- Two defects behind that, both fixed: a feed refused the project UA is now
  retried once with the browser UA the project already keeps for such hosts,
  and a feed that fails outright now keeps its existing records — with their
  original `verified.on`, so staleness reporting stays honest — instead of
  having them deleted. A family-wide floor guard refuses any run that would
  drop more than 20% of the records on disk.

### Known gaps

- `aa/aacentralohio` (Central Ohio, 852 meetings in v1.0) still returns 401 and
  is absent. Its records were deleted by the August refresh, before the
  carry-over above existed, so there was nothing left on disk to preserve.
- NA/BMLT meetings are down 2,080 (−9.3%) against v1.0. That is within the
  module's floor guard and has **not** been investigated; it may be ordinary
  churn across a federated volunteer network or the same class of fetch
  failure. Treat NA counts in this release as a lower bound.

## v1.0 — 2026-07-27

First citable release. **12,947** organizations · **136,038** sites ·
**77,714** meetings · **32,307** places · **251** sources.

First national Open Referral HSDS 3.0 export of a US help-services dataset
published with a DOI, alongside the canonical YAML, a JSON Schema, an
independent validation gate, and a datasheet following Gebru et al.
