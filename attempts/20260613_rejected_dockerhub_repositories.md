# dockerhub_repositories

- Date: 2026-06-13
- Status: rejected
- Candidate dataset: Docker Hub repository search results for `data`
- Source: `https://hub.docker.com/v2/search/repositories/?query=data&page_size=100`
- Why it looked promising: Public repository metadata with native star counts, pull counts, and official flags.
- Failure class: arbitrary_query_slice
- What happened: The accepted recipe was audited and found to be one topical repository search slice rather than a coherent container-image corpus. It emits `300` primary values, `1300` primary sample bytes, and has a median primary sample size of `100` values.
- Why more download does not save this recipe: The current recipe identity is one search term, `data`. Making it materially useful would require replacing the one-query slice with a broader repository corpus or a documented multi-query scope, which is a different recipe.
- Evidence: `reports/accepted_recipe_audit.tsv` showed `dockerhub_repositories` at `300` primary values, `1300` primary sample bytes, `3` primary sample rows, and median primary sample size `100` values before removal.
- Logs: Existing local build and verify logs for the former accepted recipe; no new acquisition failure was involved in this cleanup decision.
- Decision: Remove `dockerhub_repositories` from `datasets/` and reject this exact one-query Docker Hub search recipe.
- Retry conditions: Retry only as a materially broader homogeneous Docker Hub repository corpus with documented scope selection.
