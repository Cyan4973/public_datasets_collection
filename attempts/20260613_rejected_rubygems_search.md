# rubygems_search

- Date: 2026-06-13
- Status: rejected
- Candidate dataset: RubyGems search results for `data`
- Source: `https://rubygems.org/api/v1/search.json?query=data`
- Why it looked promising: Public package metadata with native download counters and version-download counters.
- Failure class: arbitrary_query_slice
- What happened: The accepted recipe was audited and found to be a single fixed search query rather than a coherent corpus definition. It emits only `60` primary values, `480` primary sample bytes, and has a median primary sample size of `30` values.
- Why more download does not save this recipe: The current recipe identity is exactly one search term, `data`. Scaling it honestly would require changing the query set or switching from one search slice to a broader package-corpus recipe, which is a different recipe.
- Evidence: `reports/accepted_recipe_audit.tsv` showed `rubygems_search` at `60` primary values, `480` primary sample bytes, `2` primary sample rows, and median primary sample size `30` values before removal.
- Logs: Existing local build and verify logs for the former accepted recipe; no new acquisition failure was involved in this cleanup decision.
- Decision: Remove `rubygems_search` from `datasets/` and reject this exact one-query RubyGems search recipe.
- Retry conditions: Retry only as a materially broader homogeneous RubyGems package corpus with documented scope selection.
