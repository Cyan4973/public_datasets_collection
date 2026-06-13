# openlibrary_search

- Date: 2026-06-13
- Status: rejected
- Candidate dataset: OpenLibrary search results for `machine learning`
- Source: `https://openlibrary.org/search.json?q=machine+learning&limit=100`
- Why it looked promising: Public bibliographic metadata with native edition counts, publish years, and scan/fulltext flags.
- Failure class: arbitrary_query_slice
- What happened: The accepted recipe was audited and found to be one topical search result set rather than a coherent bibliographic corpus. It emits `400` primary values, `800` primary sample bytes, and has a median primary sample size of `80` values.
- Why more download does not save this recipe: The current recipe identity is one search query, `machine learning`. To scale it honestly, the recipe would need a different corpus definition than one query slice, which makes it a different recipe.
- Evidence: `reports/accepted_recipe_audit.tsv` showed `openlibrary_search` at `400` primary values, `800` primary sample bytes, `5` primary sample rows, and median primary sample size `80` values before removal.
- Logs: Existing local build and verify logs for the former accepted recipe; no new acquisition failure was involved in this cleanup decision.
- Decision: Remove `openlibrary_search` from `datasets/` and reject this exact one-query OpenLibrary search recipe.
- Retry conditions: Retry only as a materially broader bibliographic corpus with documented scope selection.
