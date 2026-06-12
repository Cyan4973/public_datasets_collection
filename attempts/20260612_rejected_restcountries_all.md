# restcountries_all

- Date: 2026-06-12
- Status: rejected
- Candidate dataset: Rest Countries full country catalog
- Source: https://restcountries.com/
- Why it looked promising: Public country-level reference data with legitimate numeric fields and a distinct source family.
- Failure class: intrinsically_small_standalone
- What happened: The accepted recipe was audited and found to be intrinsically too small for this collection as a standalone dataset. The full country catalog is close to complete, finite, and too low-density numerically to justify a dedicated recipe.
- Evidence: `reports/accepted_recipe_audit.tsv` showed `restcountries_all` at `1740` total values and `7210` total sample bytes before removal.
- Logs: Existing local build and verify logs for the former accepted recipe; no new acquisition failure was involved in this cleanup decision.
- Decision: Remove `restcountries_all` from `datasets/` and reject it as a standalone accepted dataset.
- Retry conditions: Retry only if merged into a broader geopolitical reference bundle that materially increases numeric content.
