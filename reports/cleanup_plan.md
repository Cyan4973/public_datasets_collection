# Cleanup Plan

Date: 2026-06-15

Source of truth:
- `reports/accepted_recipe_audit.tsv`
- `reports/degenerate_series_audit.tsv`
- `reports/family_homogeneity_policy.md`
- git history through `f8ec8e1`

Current audit baseline:
- `ok`: `122`
- `below_floor`: `192`
- `broken`: `0`
- degenerate findings: `5`, all `binary_sparse`
- constant findings: `0`

## Completed

- removed empty residual directories left behind by previously rejected, blocked, or superseded recipes
- fixed report generation so quality audits cover currently accepted manifests
- removed the first tiny-dataset batches, including accepted datasets with `<= 100` values
- removed `6` tiny non-family standalones after extension triage
- removed `94` globally constant manifest series across `52` datasets
- filtered `93` constant natural samples from otherwise non-constant series

## Next: Sparse-Binary Policy

The degenerate audit now contains only sparse-binary findings. These are not
constant samples, so they need a separate policy decision before removal.

Current sparse-binary rows:
- `noaa_ghcn_daily_snwd_by_station`: `2`
- `noaa_ghcn_daily_wesd_by_station`: `2`
- `noaa_isd_lite`: `1`

## Next: Easy Removal Batch

Prune the smallest non-family below-floor standalones first.

Priority target:
- non-family recipes with `<= 500` total primary values
- no credible path to floor without changing recipe identity
- current count: `35`

## Next: Family Cleanup

Resolve fragmented accepted families without violating homogeneity.

Priority families:
- `fred_*`: `23`
- `world_bank_*`: `16`
- `owid_*`: `20`
- `imf_*`: `7`
- `eurostat_*`: `7`
- `sec_companyfacts_*`: `5`

## Later: Rewrite / Expand Survivors

Revisit below-floor recipes that may survive if widened materially by pagination,
time range, or entity coverage while staying reproducible and homogeneous.
