# dryad_search

- Date: 2026-06-15
- Status: rejected
- Candidate dataset: Dryad search API slice
- Source: `https://datadryad.org/api/v2/search`
- Why it looked promising: Public research-data repository metadata with numeric row-level fields from a distinct source family.
- Failure class: intrinsically_small_standalone
- What happened: After globally constant fields were removed, the recipe had only `100` total primary values, `360` primary sample bytes, `5` sample rows, and median sample size `20` values.
- Why more download does not save this recipe: This exact recipe is a single small search page. A viable Dryad recipe would need materially broader pagination or a different homogeneous sample design.
- Evidence: `reports/accepted_recipe_audit.tsv` showed `dryad_search` at `100` primary values and `aggregate_floor,median_sample_floor` before removal.
- Decision: Remove `dryad_search` from `datasets/` and reject this standalone recipe shape.
- Retry conditions: Retry only as a larger homogeneous Dryad metadata recipe with enough entity coverage and defensible sample boundaries.
