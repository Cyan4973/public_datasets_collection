# figshare_articles

- Date: 2026-06-15
- Status: rejected
- Candidate dataset: Figshare articles first-page snapshot
- Source: `https://api.figshare.com/v2/articles?page_size=100`
- Why it looked promising: Public research repository article metadata with native numeric identifiers and type fields.
- Failure class: superseded_tiny_standalone
- What happened: The accepted recipe had only `300` total primary values, `1000` primary sample bytes, `3` sample rows, and median sample size `100` values.
- Why more download does not save this recipe: The source can be paginated, but this one-page recipe is not the right accepted unit. A larger `figshare_articles_large` recipe already exists and should be repaired or replaced instead.
- Evidence: `reports/accepted_recipe_audit.tsv` showed `figshare_articles` at `300` primary values with `aggregate_floor,median_sample_floor` before removal.
- Decision: Remove `figshare_articles` from `datasets/` and reject this shallow standalone.
- Retry conditions: Retry only as a materially larger homogeneous Figshare articles recipe with enough pagination and natural sample geometry to clear the floor.
