# Cleanup Plan

Date: 2026-06-12

Source of truth:
- `reports/accepted_recipe_audit.tsv`
- `reports/degenerate_series_audit.tsv`
- `reports/family_homogeneity_policy.md`
- git history through `9e2eda2`

## Step 1: Easy Hygiene Cleanup

- remove empty residual directories left behind by previously rejected, blocked, or superseded recipes
- fix report generation so quality audits only cover currently accepted recipes
- regenerate stale audit reports
- refresh `reports/cleanup_candidates.md` so it matches the current audit baseline

## Step 2: Easy Removal Batch

- prune the smallest non-family below-floor standalones first
- priority target: non-family recipes with `<= 500` total values and no credible path to floor without changing the recipe identity

## Step 3: Family Cleanup

- resolve fragmented accepted families without violating homogeneity
- priority families:
  - `sec_companyfacts_*`
  - `fred_*`
  - `eurostat_*`
  - `world_bank_*`
  - `imf_*`
  - `owid_*`

## Step 4: Rewrite / Expand Survivors

- revisit below-floor recipes that may be salvageable by widening pagination, time range, or entity coverage while staying reproducible and homogeneous

## Step 5: Constant-Series Cleanup

- first prune globally constant accepted series listed in `reports/constant_series_cleanup.md`
- filter or reject constant samples inside otherwise useful series, without removing the whole non-constant series
- do not handle sparse-binary findings in this pass; those need separate policy and review
