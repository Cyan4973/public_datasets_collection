# fred_real_gdp_quarterly

- Date: 2026-06-15
- Status: rejected
- Candidate dataset: FRED real GDP quarterly single-series recipe
- Source: `https://fred.stlouisfed.org/graph/fredgraph.csv`
- Why it looked promising: Official macroeconomic time series from FRED, clean numeric values, and deterministic public CSV access.
- Failure class: intrinsically_small_standalone
- What happened: The accepted recipe was audited after the constant-series cleanup and remained far below the current floor, with only `40` total primary values, `160` primary sample bytes, `10` sample rows, and median sample size `4` values.
- Why more download does not save this recipe: This exact recipe is a single GDPC1 quarterly series over a fixed `2015..2024` window emitted as one yearly sample. Extending it or bundling it should be treated as a different homogeneous FRED-family recipe, not as this standalone.
- Evidence: `reports/accepted_recipe_audit.tsv` showed `fred_real_gdp_quarterly` at `40` primary values and `aggregate_floor,median_sample_floor` before removal.
- Decision: Remove `fred_real_gdp_quarterly` from `datasets/` and reject this standalone recipe shape.
- Retry conditions: Retry only as part of a materially larger, homogeneous FRED macro bundle with defensible sample boundaries.
