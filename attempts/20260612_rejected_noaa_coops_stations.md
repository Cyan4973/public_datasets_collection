# noaa_coops_stations

- Date: 2026-06-12
- Status: rejected
- Candidate dataset: NOAA CO-OPS station catalog
- Source: https://api.tidesandcurrents.noaa.gov/mdapi/prod/webapi/stations.json
- Why it looked promising: Public operational marine observation source with real station metadata and a clear relationship to already accepted measurement recipes.
- Failure class: intrinsically_small_standalone
- What happened: The accepted recipe was audited and found to be intrinsically too small for this collection as a standalone dataset. The station catalog is finite and better treated as supporting metadata for measurement datasets than as its own training dataset.
- Evidence: `reports/accepted_recipe_audit.tsv` showed `noaa_coops_stations` at `2107` total values and `7525` total sample bytes before removal.
- Logs: Existing local build and verify logs for the former accepted recipe; no new acquisition failure was involved in this cleanup decision.
- Decision: Remove `noaa_coops_stations` from `datasets/` and reject it as a standalone accepted dataset.
- Retry conditions: Retry only if merged into a richer NOAA CO-OPS bundle or used strictly as attached metadata for accepted measurement recipes.
