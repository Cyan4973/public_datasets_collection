# npm_search_packages

- Date: 2026-06-15
- Status: rejected
- Candidate dataset: npm package search first-page snapshot
- Source: `https://registry.npmjs.org/-/v1/search?text=data&size=100`
- Why it looked promising: Public package registry search metadata with native download and score metrics.
- Failure class: superseded_tiny_standalone
- What happened: The accepted recipe had only `500` total primary values, `2600` primary sample bytes, `5` sample rows, and median sample size `100` values.
- Why more download does not save this recipe: The query term `data` is arbitrary, and a larger `npm_search_packages_large` recipe already exists. The current one-page recipe should not remain accepted.
- Evidence: `reports/accepted_recipe_audit.tsv` showed `npm_search_packages` at `500` primary values with `aggregate_floor,median_sample_floor` before removal.
- Decision: Remove `npm_search_packages` from `datasets/` and reject this shallow standalone.
- Retry conditions: Retry only as a materially larger homogeneous npm package metadata recipe with an explicit broad scope, not this one-page query.
