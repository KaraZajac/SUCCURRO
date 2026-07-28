# Release checklist — cutting a citable DOI snapshot

The gate for tagging a frozen, permanently citable version. A DOI'd dataset is
downloaded, cited, and built on by people who will never read the caveats in
this repository — the bar is higher than "the site looks right."

Legend: **[auto]** = tooled, runnable · **[K]** = needs Kara's judgment or account.

## 0 · Machine gate (must be green at the tagged commit)

- [ ] **[auto]** `make verify` — schema conformance + referential integrity +
      freshness checks, zero errors.
- [ ] **[auto]** `make build` reproduces the dataset from cached sources without
      errors (module-level skip-and-report is acceptable and logged).
- [ ] **[auto]** `python3 publish/export_release.py --tag <tag>` succeeds; the
      bundle's `SHA256SUMS` verifies (`sha256sum -c`).
- [ ] **[auto]** Site builds: `cd site && npm run build` (render test over every
      page, including Pagefind indexing).
- [ ] **[auto]** CI green on the tagged commit.

## 1 · Provenance and rights

- [ ] **[auto]** Every record cites at least one source record (validator
      enforces; dangling refs are hard errors).
- [ ] **[auto]** `python3 -m pipeline.archive` run — Wayback `archive_url` on
      every source record that has a live URL; report the unarchived remainder.
- [ ] **[K]** `DATA-RIGHTS.md` per-source table matches reality, including the
      **not-collected** list (sources whose terms prohibit collection) and any
      permissions granted since the last release.
- [ ] **[K]** Sources under a permission clock are in their correct state — no
      record from a source that has not answered *and* has restrictive terms.
- [ ] **[K]** Any source that granted permission has its terms recorded in
      `DATA-RIGHTS.md` and honored in the module (attribution wording, cadence,
      exclusions).

## 2 · Safety posture

- [ ] **[auto]** No record tagged `domestic-violence` or `dv_confidential`
      carries a street address (validator + per-module asserts).
- [ ] **[auto]** Recovery meeting records carry no personal contact fields
      (spot-check for `@` in notes; fellowship anonymity).
- [ ] **[auto]** Staleness report reviewed: how many safety-critical records
      exceed their threshold, and whether the site suppression is working.
- [ ] **[K]** Any takedown request received since the last release has been
      honored, and the source module prevents re-ingestion.

## 3 · Honest representation

- [ ] **[K]** `publish/DATASHEET.md` counts, coverage percentages, and
      limitations match `stats.json` from this build.
- [ ] **[K]** Coverage claims are stated as coverage *of sources collected*,
      never as "all services in the US." The BMF gap audit is cited for the
      categorical unevenness.
- [ ] **[K]** No record is described as "verified" beyond what actually
      happened: `verified.method` is `api` / `scrape` / `human`, and the
      datasheet explains that most stamps mean "matched the source on that
      date," not independent confirmation.
- [ ] **[K]** Known-stale or provisional records carry `provisional: true`.

## 4 · Metadata and citation

- [ ] **[K]** `.zenodo.json` — title, description, keywords, license, ORCID,
      and `related_identifiers` current.
- [ ] **[K]** `CITATION.cff` — abstract and counts current; concept DOI filled
      in (after the first release mints it).
- [ ] **[K]** `README.md` — DOI badge, counts, and the "what this is / is not"
      framing current.
- [ ] **[auto]** `docs/sources.md` registry regenerated/updated with per-source
      record counts from this build.

## 5 · Cutting the release

1. **[K]** In Zenodo: log in with GitHub, open *Account → GitHub*, and flip the
   switch on `KaraZajac/SUCCURRO`. **This must happen before the release** —
   Zenodo only archives releases published after the webhook exists.
2. **[auto]** Tag and publish the GitHub release:
   `gh release create v1.0 --title "SUCCURRO v1.0" --notes-file <notes>`
   Zenodo archives the repository snapshot (which contains the canonical
   `data/` YAML) and mints a version DOI plus a concept DOI.
3. **[K]** Optionally upload `release/succurro-<tag>/` (JSONL + HSDS + schema +
   stats) to the Zenodo deposit before publishing it — the GitHub integration
   archives the repo source zip, not release assets, so the convenience bundle
   only appears if attached manually.
4. **[K]** Copy the **concept** DOI (the one that always resolves to the latest
   version) into `CITATION.cff`, the README badge, and `docs/prior-art.md` if
   it cites the dataset.
5. **[auto]** Commit those DOI updates; they land in the *next* version, which
   is expected and fine.

## 6 · After release

- [ ] **[K]** Zenodo record: check the license, creators/ORCID, and that the
      description rendered correctly.
- [ ] **[K]** Announce where it matters (Open Referral community, relevant
      practitioner lists) — coverage grows fastest through the networks whose
      data it already carries.
- [ ] **[K]** Note the release in `CHANGELOG.md` with the counts.
