# GBIF Occurrence 2024 Coordinate Sample

Accepted replacement for the below-floor `gbif_occurrence` and
`gbif_occurrence_large` recipes.

This recipe collects a fixed GBIF occurrence search scope:
`hasCoordinate=true`, `occurrenceStatus=PRESENT`, and an event-date window from
`2024-01-01` through `2024-01-31`. It emits homogeneous numeric columns from
the occurrence table: occurrence keys, taxon hierarchy keys, and coordinates.

Natural sample boundary: one bounded GBIF occurrence table column for the fixed
query scope. This replaces the old current-feed first-page snapshots with a
reproducible date-window sample.

Run:

```bash
bash datasets/gbif_occurrence_2024_coordinate_sample/download.sh
bash datasets/gbif_occurrence_2024_coordinate_sample/build.sh
bash datasets/gbif_occurrence_2024_coordinate_sample/verify.sh
```

Use `DRY_RUN=1` to inspect the request plan without fetching. The GBIF
occurrence API caps pages at 300 records; this recipe intentionally downloads a
fixed bounded sample of 40 pages, 12,000 records before filtering. It does not
claim to exhaust the full January 2024 GBIF occurrence window, which contains
millions of records. Event-date components are intentionally not emitted because
the fixed month window would make year/month constants and many GBIF records are
month-level events with no day value.
