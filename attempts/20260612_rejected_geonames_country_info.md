# geonames_country_info

- Date: 2026-06-12
- Status: rejected
- Candidate dataset: GeoNames country info table
- Source: https://download.geonames.org/export/dump/countryInfo.txt
- Why it looked promising: Public geospatial reference data with native numeric attributes such as population, area, and country-specific identifiers.
- Failure class: intrinsically_small_standalone
- What happened: The accepted recipe was audited and found to be intrinsically too small for this collection as a standalone dataset. The country table is effectively complete, finite, and too low-density to justify a dedicated recipe.
- Evidence: `reports/accepted_recipe_audit.tsv` showed `geonames_country_info` at `1764` total values and `6300` total sample bytes before removal.
- Logs: Existing local build and verify logs for the former accepted recipe; no new acquisition failure was involved in this cleanup decision.
- Decision: Remove `geonames_country_info` from `datasets/` and reject it as a standalone accepted dataset.
- Retry conditions: Retry only if merged into a broader geospatial reference bundle where the combined numeric payload is meaningful enough to clear the floor.
