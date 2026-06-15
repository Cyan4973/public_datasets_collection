# crossref_funders

- Date: 2026-06-15
- Status: rejected
- Candidate dataset: Crossref funders first-page snapshot
- Source: `https://api.crossref.org/funders?rows=100`
- Why it looked promising: Public funder registry metadata with native count-like fields.
- Failure class: superseded_tiny_standalone
- What happened: The accepted recipe had only `400` total primary values, `1000` primary sample bytes, `4` sample rows, and median sample size `100` values.
- Why more download does not save this recipe: The funder registry is pageable, but this one-page recipe is not the right accepted unit. A larger `crossref_funders_large` recipe already exists and should be repaired or replaced instead.
- Evidence: `reports/accepted_recipe_audit.tsv` showed `crossref_funders` at `400` primary values with `aggregate_floor,median_sample_floor` before removal.
- Decision: Remove `crossref_funders` from `datasets/` and reject this shallow standalone.
- Retry conditions: Retry only as a materially larger homogeneous Crossref funder registry recipe with enough pagination and natural sample geometry to clear the floor.
