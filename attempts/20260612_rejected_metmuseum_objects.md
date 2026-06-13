# metmuseum_objects

- Date: 2026-06-12
- Status: rejected
- Candidate dataset: Met Museum object ids for `sunflower` search
- Source: `https://collectionapi.metmuseum.org/public/collection/v1/search?hasImages=true&q=sunflower`
- Why it looked promising: Public museum collection API with native numeric object identifiers.
- Failure class: intrinsically_small_standalone
- What happened: The accepted recipe was audited and found to be a single search-term result set with only `70` total values and `280` total sample bytes.
- Why more download does not save this recipe: The current recipe identity is one themed search query and the output is only object IDs. The query response already returns the full object-id set for that query. Making it useful would require a different scope, such as a broader corpus or detailed object metadata recipe, not more download of the same `sunflower` search.
- Evidence: `reports/accepted_recipe_audit.tsv` showed `metmuseum_objects` at `70` total values, `280` total sample bytes, and `1` sample row before removal.
- Logs: Existing local build and verify logs for the former accepted recipe; no new acquisition failure was involved in this cleanup decision.
- Decision: Remove `metmuseum_objects` from `datasets/` and reject it as a standalone accepted dataset.
- Retry conditions: Retry only as a materially broader Met collection recipe with a coherent non-query-arbitrary scope.
