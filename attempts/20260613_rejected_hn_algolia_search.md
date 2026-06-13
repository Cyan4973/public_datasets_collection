# hn_algolia_search

- Date: 2026-06-13
- Status: rejected
- Candidate dataset: Hacker News Algolia story search results for `climate`
- Source: `https://hn.algolia.com/api/v1/search?query=climate&tags=story&hitsPerPage=100`
- Why it looked promising: Public community metadata with native points, comment counts, timestamps, and reply counts.
- Failure class: arbitrary_query_slice
- What happened: The accepted recipe was audited and found to be one topical story search slice rather than a coherent discussion corpus. It emits `400` primary values, `1600` primary sample bytes, and has a median primary sample size of `100` values.
- Why more download does not save this recipe: The current recipe identity is one search query, `climate`. Broadening it materially would require changing the topic selection or moving to a different archival corpus strategy, which is a different recipe.
- Evidence: `reports/accepted_recipe_audit.tsv` showed `hn_algolia_search` at `400` primary values, `1600` primary sample bytes, `4` primary sample rows, and median primary sample size `100` values before removal.
- Logs: Existing local build and verify logs for the former accepted recipe; no new acquisition failure was involved in this cleanup decision.
- Decision: Remove `hn_algolia_search` from `datasets/` and reject this exact one-query Hacker News search recipe.
- Retry conditions: Retry only as a materially broader discussion corpus with documented scope selection.
