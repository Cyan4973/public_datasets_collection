# census_geocoder

- Date: 2026-06-12
- Status: rejected
- Candidate dataset: Census geocoder single-query result
- Source: https://geocoding.geo.census.gov/
- Why it looked promising: Public government geospatial service with legitimate numeric coordinates and identifiers.
- Failure class: intrinsically_small_standalone
- What happened: The accepted recipe was audited and found to be a single-query geocoder result with only `6` total values and `32` sample bytes. That is a lookup artifact, not a meaningful standalone dataset.
- Evidence: `reports/accepted_recipe_audit.tsv` showed `census_geocoder` at `6` total values, `32` total sample bytes, and `6` sample rows before removal.
- Logs: Existing local build and verify logs for the former accepted recipe; no new acquisition failure was involved in this cleanup decision.
- Decision: Remove `census_geocoder` from `datasets/` and reject it as a standalone accepted dataset.
- Retry conditions: Retry only through a materially larger Census geocoding recipe with a deterministic multi-query corpus or a richer bulk geographic source.
