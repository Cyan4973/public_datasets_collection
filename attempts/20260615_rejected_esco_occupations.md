# esco_occupations

- Date: 2026-06-15
- Status: rejected
- Candidate dataset: ESCO occupation search for data-related occupations
- Source: `https://ec.europa.eu/esco/api/search?type=occupation&text=data&limit=100`
- Why it looked promising: Public occupational taxonomy endpoint with structured occupation codes.
- Failure class: intrinsically_small_standalone
- What happened: The accepted recipe had only `142` total primary values, `213` primary sample bytes, `2` sample rows, and median sample size `71` values.
- Why more download does not save this recipe: A full ESCO taxonomy recipe might be possible, but this query is narrow and the current numeric payload is mostly categorical code components.
- Evidence: `reports/accepted_recipe_audit.tsv` showed `esco_occupations` at `142` primary values with `aggregate_floor,median_sample_floor` before removal.
- Decision: Remove `esco_occupations` from `datasets/` and reject this standalone recipe shape.
- Retry conditions: Retry only as a full or otherwise broad ESCO taxonomy recipe with stronger native numeric material and enough natural sample size to clear the floor.
