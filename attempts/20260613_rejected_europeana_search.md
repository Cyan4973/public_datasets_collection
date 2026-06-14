# europeana_search

- Date: 2026-06-13
- Status: rejected
- Candidate dataset: Europeana search-response metadata for `query=art`
- Source: `https://api.europeana.eu/record/v2/search.json?wskey=apidemo&query=art&rows=100`
- Why it looked promising: Public cultural-heritage API response with native numeric fields and a straightforward JSON build path.
- Failure class: arbitrary_query_slice
- What happened: The accepted recipe was audited and found to be one search-result page with ranking and record-bookkeeping fields rather than a coherent source dataset. It emits `500` primary values, `2300` primary sample bytes, and has a median primary sample size of `100` values.
- Why more download does not save this recipe: The current recipe identity is one topical search query, `art`. Paging further only deepens the same arbitrary search slice. A real Europeana dataset would need a different corpus boundary such as a stable collection, institution, or other non-search scope, which makes it a different recipe.
- Evidence: `reports/accepted_recipe_audit.tsv` showed `europeana_search` at `500` primary values, `2300` primary sample bytes, `5` primary sample rows, and median primary sample size `100` values before removal. The builder extracted only `completeness`, `index`, `score`, and created/updated timestamps from `src["items"]`.
- Logs: Existing local build and verify logs for the former accepted recipe; no new acquisition failure was involved in this cleanup decision.
- Decision: Remove `europeana_search` from `datasets/` and reject this exact Europeana search-result metadata recipe.
- Retry conditions: Retry only as a materially broader Europeana corpus with a stable non-search boundary.
