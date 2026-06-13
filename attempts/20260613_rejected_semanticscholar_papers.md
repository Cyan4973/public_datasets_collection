# semanticscholar_papers

- Date: 2026-06-13
- Status: rejected
- Candidate dataset: Semantic Scholar paper search results for `machine learning`
- Source: `https://api.semanticscholar.org/graph/v1/paper/search?query=machine%20learning&limit=100&fields=year,citationCount,referenceCount`
- Why it looked promising: Public scholarly metadata with native years, citation counts, and reference counts.
- Failure class: arbitrary_query_slice
- What happened: The accepted recipe was audited and found to be a topical paper search slice rather than a corpus definition. It emits `300` primary values, `1000` primary sample bytes, and has a median primary sample size of `100` values.
- Why more download does not save this recipe: The current recipe identity is one search query, `machine learning`. Scaling it honestly would require redefining the query set or switching to a broader scholarly corpus recipe, which is materially different.
- Evidence: `reports/accepted_recipe_audit.tsv` showed `semanticscholar_papers` at `300` primary values, `1000` primary sample bytes, `3` primary sample rows, and median primary sample size `100` values before removal.
- Logs: Existing local build and verify logs for the former accepted recipe; no new acquisition failure was involved in this cleanup decision.
- Decision: Remove `semanticscholar_papers` from `datasets/` and reject this exact one-query Semantic Scholar search recipe.
- Retry conditions: Retry only as a materially broader homogeneous scholarly-metadata recipe with documented corpus scope.
