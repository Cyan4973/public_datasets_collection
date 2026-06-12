# nominatim_berlin

- Date: 2026-06-12
- Status: rejected
- Candidate dataset: Nominatim Berlin geocoder lookup
- Source: https://nominatim.openstreetmap.org/
- Why it looked promising: Public geospatial lookup service with native coordinates and ranking metadata.
- Failure class: intrinsically_small_standalone
- What happened: The accepted recipe was audited and found to be a single-query lookup result with only `6` total values and `34` sample bytes. That is too thin and too query-specific to justify an accepted standalone dataset.
- Evidence: `reports/accepted_recipe_audit.tsv` showed `nominatim_berlin` at `6` total values, `34` total sample bytes, and `6` sample rows before removal.
- Logs: Existing local build and verify logs for the former accepted recipe; no new acquisition failure was involved in this cleanup decision.
- Decision: Remove `nominatim_berlin` from `datasets/` and reject it as a standalone accepted dataset.
- Retry conditions: Retry only through a materially larger deterministic geocoding corpus or a richer OpenStreetMap-derived bulk dataset.
