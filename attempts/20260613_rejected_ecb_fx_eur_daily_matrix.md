# ecb_fx_eur_daily_matrix

- Date: 2026-06-13
- Status: rejected
- Candidate dataset: ECB daily FX EUR matrix with one yearly sample per currency pair
- Source: `https://data-api.ecb.europa.eu/service/data/EXR/`
- Why it looked promising: Public official market data with one coherent FX family, strong aggregate totals, and a clean homogeneous consolidation of the earlier thin pair recipes.
- Failure class: tiny_sample_geometry
- What happened: The accepted recipe was re-audited under the new sample-geometry rule and failed because its samples are uniformly too small. It emits `48659` total values and `194636` total sample bytes, but the median sample has only `256` values (`1024` bytes) because the recipe splits each currency pair into one sample per year.
- Why more download does not save this recipe: The current recipe identity is specifically one yearly sample per currency pair over a pinned `2015..2024` window. Extending the year range only creates more year-sized samples of essentially the same shallow depth. Making samples materially larger would require changing the sample boundary from per-year slices to multi-year or full-history series, which is a different recipe shape.
- Evidence: `reports/accepted_recipe_audit.tsv` showed `ecb_fx_eur_daily_matrix` at `48659` total values, `194636` total sample bytes, `190` sample rows, and median sample size `256` values before removal.
- Logs: Existing local build and verify logs for the former accepted recipe; no new acquisition failure was involved in this cleanup decision.
- Decision: Remove `ecb_fx_eur_daily_matrix` from `datasets/` and reject this exact yearly-sliced recipe shape.
- Retry conditions: Retry only as a materially different ECB FX recipe with larger sample boundaries, not as yearly pair slices.

