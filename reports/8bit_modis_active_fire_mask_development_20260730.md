# MODIS Active-Fire Mask UInt8 Development — 2026-07-30

`modis_active_fire_mask_u8` adds satellite active-fire confidence maps to the
8-bit corpus. Existing byte-valued Earth-observation recipes cover land cover,
surface-water occurrence, scene classification, planetary infrared intensity,
weather radar, and snow/ice state. MOD14A2 contributes a different field:
sparse fire detections embedded in categorical water, cloud, and non-fire land
backgrounds over an 8-day observation window.

The inventory started from committed `datasets/*/manifest.toml`,
`attempts/dataset_status.tsv`, and `reports/accepted_recipe_audit.tsv`. No
membership or coverage decision used `.data/samples/`.

## Source, scope, and license

The source is NASA LP DAAC's MODIS/Terra Thermal Anomalies/Fire 8-Day L3
Global 1 km SIN Grid, Collection 6.1 (`MOD14A2.061`), mirrored as Cloud
Optimized GeoTIFFs by Microsoft Planetary Computer. The recipe cites DOI
`10.5067/MODIS/MOD14A2.061`.

Planetary Computer's generic STAC license field says `proprietary`, but its
collection-specific `rel=license` link delegates to the official LP DAAC data
policy and identifies NASA LP DAAC as producer/licensor. That policy explicitly
states that, unless content has a separate use restriction, data from a
NASA-led mission are CC0 and have no use restrictions. No separate MOD14A2
restriction is present. The manifest therefore records CC0 while retaining the
DOI, attribution, collection version, exact item IDs, and source dates.

The bounded scope uses Terra only and fixes four MODIS sinusoidal tiles—western
North America (`h08v05`), the Amazon basin (`h12v09`), southern Africa
(`h20v11`), and Australia (`h30v11`)—at three 2024 composite start dates:
day-of-year 001, 129, and 257. Exact Collection 6.1 item IDs are pinned. The
twelve source COGs total `426,570` bytes.

The STAC search exposed duplicate May catalog aliases whose newer item IDs
pointed to older-named raster blobs. Selection required the item ID to match
the FireMask filename, yielding twelve unique and self-consistent item/asset
pairs.

## Representation and validation

Every source is a classic little-endian TIFF with a `1200 x 1200` primary
`uint8` plane, two overview IFDs, nine `512 x 512` Deflate tiles, and predictor
1. Build reads only the full-resolution primary IFD, decompresses each tile,
removes TIFF edge padding, and reconstructs the complete raster in source row
order. It does not preserve TIFF bytes, use overviews, crop the primary grid,
concatenate items, resample, quantize, or remap classes.

Build and independent verification enforce:

- exactly twelve pinned item IDs and one complete natural tile per sample
- exactly `1,440,000` unchanged uint8 values per sample
- only documented FireMask codes `0..9`
- at least 0.1% minority values and at least one code `7`, `8`, or `9` fire
  pixel in every sample
- four regions with three dates each and three dates with four regions each
- exact index sizes, per-sample histograms, aggregate totals, and the 1 GB cap

## Realized output

Build and independent verification passed:

- natural samples: `12` complete 8-day FireMask tiles
- values per sample: `1,440,000` (fixed shape `1200 x 1200`)
- primary values and bytes: `17,280,000`
- per-sample minority fraction: `0.002272` to `0.223390`
- aggregate fire-confidence pixels (`7..9`): `12,230`
- aggregate code counts:
  - `3`: `1,359,963`
  - `4`: `47,280`
  - `5`: `15,860,105`
  - `6`: `422`
  - `7`: `805`
  - `8`: `6,714`
  - `9`: `4,711`

The September Amazon sample contains `7,183` fire-confidence pixels, while the
January western-North-America sample contains only `36`. This spatial and
seasonal variation, together with large water/land boundaries and sparse fire
clusters, is the intended new compression shape.
