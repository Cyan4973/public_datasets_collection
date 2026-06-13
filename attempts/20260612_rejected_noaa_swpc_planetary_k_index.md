# noaa_swpc_planetary_k_index

- Date: 2026-06-12
- Status: rejected
- Candidate dataset: NOAA SWPC planetary K-index product feed
- Source: `https://services.swpc.noaa.gov/products/noaa-planetary-k-index.json`
- Why it looked promising: Public space-weather telemetry with native numeric time, index, and station-count fields.
- Failure class: intrinsically_small_standalone
- What happened: The accepted recipe was audited and found to be too small as a standalone dataset, with only `252` total values and `693` total sample bytes.
- Why more download does not save this recipe: The current recipe identity is one bounded SWPC product endpoint. Refetching the same product only gives another small rolling feed of the same endpoint rather than a materially larger corpus. To clear the floor, the recipe would need a broader historical archive or a different SWPC product family, which is materially different from this exact endpoint recipe.
- Evidence: `reports/accepted_recipe_audit.tsv` showed `noaa_swpc_planetary_k_index` at `252` total values, `693` total sample bytes, and `4` sample rows before removal.
- Logs: Existing local build and verify logs for the former accepted recipe; no new acquisition failure was involved in this cleanup decision.
- Decision: Remove `noaa_swpc_planetary_k_index` from `datasets/` and reject it as a standalone accepted dataset.
- Retry conditions: Retry only as a materially broader space-weather time-series recipe with documented historical or multi-product scope.
