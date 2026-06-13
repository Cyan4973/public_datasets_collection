# bls_cpi_series

- Date: 2026-06-12
- Status: rejected
- Candidate dataset: BLS CPI-U all-items single series
- Source: `https://api.bls.gov/publicAPI/v2/timeseries/data/CUSR0000SA0`
- Why it looked promising: Legitimate public macroeconomic time series with native monthly numeric observations.
- Failure class: intrinsically_small_standalone
- What happened: The accepted recipe was audited and found to be a single-series slice with only `96` total values and `192` total sample bytes.
- Why more download does not save this recipe: The current recipe identity is one CPI series. Extending the time range to the full available monthly history still leaves one finite monthly sequence and remains far below the repository floor. To become useful, it needs to be merged into a broader homogeneous BLS or inflation family recipe, not kept as a standalone.
- Evidence: `reports/accepted_recipe_audit.tsv` showed `bls_cpi_series` at `96` total values, `192` total sample bytes, and `4` sample rows before removal.
- Logs: Existing local build and verify logs for the former accepted recipe; no new acquisition failure was involved in this cleanup decision.
- Decision: Remove `bls_cpi_series` from `datasets/` and reject it as a standalone accepted dataset.
- Retry conditions: Retry only as part of a materially broader homogeneous macro or BLS family recipe.
