# Family Homogeneity Policy

This policy governs cleanup of over-fragmented accepted recipes.

The goal is not to make recipes larger by any means necessary. The goal is to keep accepted recipes both:

- large enough to matter, and
- materially coherent.

## Core Rule

A replacement family recipe is acceptable only if it is homogeneous by:

1. source family
2. material type
3. generation process
4. cadence
5. unit semantics

Sharing only the same API, vendor, portal, or organization is not enough.

## Good Consolidation

- many ECB daily FX pair series combined into one FX matrix family
- many station-series of the same physical quantity combined into one family
- multiple closely related SEC filing metrics combined only when they remain one coherent financial-statement material group

## Bad Consolidation

- FX rates mixed with stock volume
- unemployment mixed with emissions
- pageviews mixed with weather observations
- arbitrary World Bank indicators bundled only because they come from the same API
- arbitrary OWID indicators bundled only because they live in the same CSV

## Decision Rule

For a fragmented family, choose one of these:

1. consolidate into a homogeneous bundle
2. split into a few homogeneous bundles
3. remove the thin standalones if no coherent consolidation exists

Do not choose:

4. a single mixed bundle that clears the size floor but destroys semantic coherence

## Immediate Application

- `ecb_fx_*`: good consolidation target
- `fred_*`: likely multiple bundles, not one
- `world_bank_*`: multiple bundles or removals, not one
- `imf_*`: multiple bundles or removals, not one
- `owid_*`: multiple bundles or removals, not one
- `eurostat_*`: multiple bundles or removals, not one
- `sec_companyfacts_*`: only consolidate if the metric set remains financially coherent
