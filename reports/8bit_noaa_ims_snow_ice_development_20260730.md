# NOAA IMS Snow and Ice UInt8 Development — 2026-07-30

`noaa_ims_snow_ice_cover_u8` adds operational cryosphere analysis grids to the
8-bit corpus. Existing byte-valued rasters cover land cover, surface-water
occurrence, scene classification, microscopy masks, and weather radar. IMS
instead provides a daily categorical state field with strong seasonal snow and
ice evolution.

The inventory started from committed `datasets/*/manifest.toml`,
`attempts/dataset_status.tsv`, and `reports/accepted_recipe_audit.tsv`. No
membership or coverage decision used `.data/samples/`.

## Source, scope, and license

The source is NOAA/U.S. National Ice Center IMS Daily Northern Hemisphere Snow
and Ice Analysis, Version 1, distributed by NSIDC as product G02156 and cited
by DOI `10.7265/N52R3PMC`. It is an official U.S. Government environmental
data product and is recorded as public-domain material. The recipe preserves
the product citation, NOAA/USNIC/NSIDC attribution, product version, and source
dates.

The bounded scope is the complete 4 km analysis at 00 UTC on the first day of
each month in leap year 2024. The twelve exact source files total `5,275,404`
compressed bytes. Each decompresses to an ASCII product with a documented
30-line header followed by one complete `6144 x 6144` grid.

The first attempted URL omitted the filename's `_00UTC_` segment and returned
HTTP 404. A user-run official archive listing established the exact current
filenames; the corrected downloader fetched and validated all twelve files.

## Representation and validation

The source grid contains numeric category codes `0..4`. Build strips the
documented header and writes those codes unchanged, in source row-major order,
as one byte per cell. Background/outside-domain code `0` is preserved because
it is a documented product value. The recipe does not retain gzip bytes,
concatenate days, crop, resample, quantize, or remap classes.

Download validation requires successful HTTP retrieval, a valid gzip stream,
a bounded compressed size, and a plausible decompressed size. Build and verify
independently enforce:

- exactly twelve pinned analysis dates
- exactly `6144 x 6144` values per natural daily-grid sample
- only documented category codes `0..4`
- at least four distinct codes in every grid
- unique dates, exact index sizes, histograms, and aggregate totals
- the repository's aggregate, median-sample, and 1 GB output bounds

## Realized output

Build and independent verification passed:

- natural samples: `12` complete daily grids
- values per sample: `37,748,736`
- primary values and bytes: `452,984,832`
- median natural sample: `37,748,736` values
- aggregate code counts:
  - `0`: `121,465,476`
  - `1`: `210,918,499`
  - `2`: `96,306,128`
  - `3`: `7,516,404`
  - `4`: `16,778,325`

The snow-class population falls from `2,716,514` cells in February to
`155,864` in August and rises to `2,429,309` in December. Ice-class counts also
show a pronounced seasonal cycle, confirming that the material is neither
constant nor a repeated static mask.
