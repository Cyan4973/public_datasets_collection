# ensembl_species

- Date: 2026-06-12
- Status: rejected
- Candidate dataset: Ensembl species catalog
- Source: https://rest.ensembl.org/info/species
- Why it looked promising: Public biological reference data from a credible source, with stable numeric fields such as taxonomy identifiers and release metadata.
- Failure class: intrinsically_small_standalone
- What happened: The accepted recipe was audited and found to be intrinsically too small for this collection as a standalone dataset. The species catalog is already close to complete, has low numeric density, and does not cross the repository usefulness floor even with the current full-source pull.
- Evidence: `reports/accepted_recipe_audit.tsv` showed `ensembl_species` at `1392` total values and `2784` total sample bytes before removal.
- Logs: Existing local build and verify logs for the former accepted recipe; no new acquisition failure was involved in this cleanup decision.
- Decision: Remove `ensembl_species` from `datasets/` and reject it as a standalone accepted dataset.
- Retry conditions: Retry only as part of a richer Ensembl family recipe, such as genes, transcripts, variants, or another substantially larger subset with meaningful numeric content.
