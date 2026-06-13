# ror_organizations

- Date: 2026-06-12
- Status: rejected
- Candidate dataset: ROR organization search response for `stanford`
- Source: `https://api.ror.org/organizations?query=stanford`
- Why it looked promising: Public research-organization metadata with native counts and establishment year fields.
- Failure class: intrinsically_small_standalone
- What happened: The accepted recipe was audited and found to be an arbitrary single-query search slice with only `54` total values and `63` total sample bytes.
- Why more download does not save this recipe: The current recipe identity is one query string, not a full organization corpus. Paging deeper on the same search query only deepens an arbitrary topical slice and does not produce a coherent standalone dataset. A meaningful fix would be a different ROR acquisition recipe, not more download of `query=stanford`.
- Evidence: `reports/accepted_recipe_audit.tsv` showed `ror_organizations` at `54` total values, `63` total sample bytes, and `6` sample rows before removal.
- Logs: Existing local build and verify logs for the former accepted recipe; no new acquisition failure was involved in this cleanup decision.
- Decision: Remove `ror_organizations` from `datasets/` and reject it as a standalone accepted dataset.
- Retry conditions: Retry only as a materially broader and more coherent ROR corpus recipe.
