# biorxiv_details

- Date: 2026-06-15
- Status: rejected
- Candidate dataset: bioRxiv details API slice
- Source: `https://api.biorxiv.org/details/biorxiv/2024-01-01/2024-01-01`
- Why it looked promising: Public scholarly metadata with numeric row-level fields from a distinct source family.
- Failure class: intrinsically_small_standalone
- What happened: After globally constant fields were removed, the recipe had only `90` total primary values, `210` primary sample bytes, `3` sample rows, and median sample size `30` values.
- Why more download does not save this recipe: This exact recipe is a one-day details slice. A useful bioRxiv recipe would need a materially broader time range and sample geometry, not this standalone.
- Evidence: `reports/accepted_recipe_audit.tsv` showed `biorxiv_details` at `90` primary values and `aggregate_floor,median_sample_floor` before removal.
- Decision: Remove `biorxiv_details` from `datasets/` and reject this standalone recipe shape.
- Retry conditions: Retry only as a larger homogeneous bioRxiv metadata recipe with enough temporal/entity coverage to clear the floor.
