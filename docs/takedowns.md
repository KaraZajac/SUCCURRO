# Takedown and correction log

Every removal or correction request received, and what was done about it. The
release checklist (`docs/RELEASE-CHECKLIST.md` §2) requires that each one has
been honored *and* that the source module prevents re-ingestion — a deletion
alone does not survive the next refresh.

Entries record the request and the remedy, never the withheld value or the
requester's identity. Suppressed contact values live as hashes in
`pipeline/curated/suppressed.yaml`; see DATA-RIGHTS.md for the mechanism.

---

## 2026-09-15 — personal number published as a site contact (USDA SFSP)

**Request.** A private individual reported that their personal phone number was
published as the contact number for the Residencial Enrique Catoni summer meal
site in Vega Baja, PR, and asked for its removal and for the source.

**Cause.** Upstream, not ours. USDA FNS Summer Meals Site Finder (2026 season)
carries the number in the `Site_Phone` field of master record
`Cycle 07_PR_SFSP_0198`; `pipeline/summermeals.py` copies `Site_Phone` verbatim.
The same number sits in `Contact_Phone` on `Cycle 08_PR_SFSP_0171` — a field we
never publish, so it never reached `data/`. Both records are for a season that
ended 2026-06-18; USDA already flags the first as expired.

**Honored.** Removed from `pr/vega-baja/residencial-enrique-catoni`, the only
record in the dataset that carried it. Re-ingestion is prevented by the
denylist introduced in the same commit, applied at `emit.replace_records`,
swept by `make suppress`, and enforced by the validation gate — verified
against seven formatting variants of the number.

**Requester told.** The exact source, both USDA master IDs, the field each uses,
and the route to a correction at USDA FNS and the Puerto Rico state agency.

**Archive.** v1.1 was cut on 2026-09-15 and deposited as
`10.5281/zenodo.22779177`. The concept DOI `10.5281/zenodo.21634583` now
resolves to it, so anyone citing or downloading SUCCURRO gets the corrected
data by default.

**Outstanding.**
- The v1.0 deposits (`10.5281/zenodo.21634584`, `10.5281/zenodo.21634634`)
  still carry the value in `sites.jsonl` and `hsds/phone.csv`. Zenodo versions
  are immutable; removing it needs a restriction request to Zenodo support.
- The value predates the removal in public git history.
- Upstream correction at USDA FNS is requested but not confirmed. Until it
  lands, the denylist is what keeps the value out on each refresh.
