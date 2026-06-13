# packagist_packages

- Date: 2026-06-13
- Status: rejected
- Candidate dataset: Packagist search results for `data`
- Source: `https://packagist.org/search.json?q=data&per_page=100`
- Why it looked promising: Public package metadata with native download and favor counters.
- Failure class: arbitrary_query_slice
- What happened: The accepted recipe was audited and found to be one fixed search result page instead of a coherent package corpus. It emits `200` primary values, `1200` primary sample bytes, and has a median primary sample size of `100` values.
- Why more download does not save this recipe: More value requires changing the search strategy or replacing the one-query slice with a broader package corpus. That is a different recipe, not more download of this exact one-page search result.
- Evidence: `reports/accepted_recipe_audit.tsv` showed `packagist_packages` at `200` primary values, `1200` primary sample bytes, `2` primary sample rows, and median primary sample size `100` values before removal.
- Logs: Existing local build and verify logs for the former accepted recipe; no new acquisition failure was involved in this cleanup decision.
- Decision: Remove `packagist_packages` from `datasets/` and reject this exact one-query Packagist search recipe.
- Retry conditions: Retry only as a materially broader homogeneous Packagist package corpus with documented scope selection.
