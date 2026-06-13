# hackernews_topstories

- Date: 2026-06-12
- Status: rejected
- Candidate dataset: Hacker News top stories id list
- Source: `https://hacker-news.firebaseio.com/v0/topstories.json`
- Why it looked promising: Public operational feed with native numeric story identifiers.
- Failure class: intrinsically_small_standalone
- What happened: The accepted recipe was audited and found to be a single ranked id list with only `500` total values and `2000` total sample bytes.
- Why more download does not save this recipe: The current recipe identity is the top-stories list endpoint itself. The endpoint is already the full list for that feed and the build emits only story ids. Clearing the floor would require fetching story detail objects or a time-indexed archive, which is a materially different recipe.
- Evidence: `reports/accepted_recipe_audit.tsv` showed `hackernews_topstories` at `500` total values, `2000` total sample bytes, and `1` sample row before removal.
- Logs: Existing local build and verify logs for the former accepted recipe; no new acquisition failure was involved in this cleanup decision.
- Decision: Remove `hackernews_topstories` from `datasets/` and reject it as a standalone accepted dataset.
- Retry conditions: Retry only as a materially broader Hacker News story-detail or time-range recipe.
