# maven_central_search

- Date: 2026-06-13
- Status: rejected
- Candidate dataset: Maven Central search results for `data`
- Source: `https://search.maven.org/solrsearch/select?q=data&rows=100&wt=json`
- Why it looked promising: Public package index metadata with native timestamps and version counts.
- Failure class: arbitrary_query_slice
- What happened: The accepted recipe was audited and found to be a single fixed search query rather than a coherent package corpus. It emits `200` primary values, `1000` primary sample bytes, and has a median primary sample size of `100` values.
- Why more download does not save this recipe: The current recipe identity is one search term, `data`, with one result window. To make it materially useful, the scope would have to become a broader package crawl or a documented multi-query corpus, which is a different recipe.
- Evidence: `reports/accepted_recipe_audit.tsv` showed `maven_central_search` at `200` primary values, `1000` primary sample bytes, `2` primary sample rows, and median primary sample size `100` values before removal.
- Logs: Existing local build and verify logs for the former accepted recipe; no new acquisition failure was involved in this cleanup decision.
- Decision: Remove `maven_central_search` from `datasets/` and reject this exact one-query Maven search recipe.
- Retry conditions: Retry only as a materially broader homogeneous Maven package corpus with documented scope selection.
