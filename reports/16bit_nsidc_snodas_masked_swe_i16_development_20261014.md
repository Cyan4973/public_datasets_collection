# SNODAS masked CONUS snow water equivalent int16 development

## Outcome

Accepted `nsidc_snodas_masked_swe_i16`: complete daily snow water equivalent (SWE) grids from the NOAA National Weather Service NOHRSC Snow Data Assimilation System (SNODAS), product code 1034. NOAA@NSIDC archives them as data set G02158, Version 1.

This family is distinct from the accepted `noaa_ims_snow_ice_cover_u8`, which is a categorical snow/ice class map on the same NSIDC host. This recipe keeps a continuous physical snowpack mass field in millimetres.

The downstream corpus already holds SWE as station daily time series (`16bit/datasets/ghcn_wesd`). SNODAS is a new source of the same physical quantity in a different structure: a gridded 2-D model analysis with a static native land mask. The novelty kind is therefore `new_source`, not a new quantity or modality. zlsim measured breadth as OK; the nearest family is `downstream:cmmd_mammography_pixel_u16` at distance 0.0857.

## Source and rights

- Source: NOAA@NSIDC anonymous HTTPS archive, `https://noaadata.apps.nsidc.org/NOAA/G02158/masked/YYYY/MM_Mon/SNODAS_YYYYMMDD.tar`.
- Members fetched: only `us_ssmv11034tS__T0001TTNATS<date>05HP001.dat.gz` and the matching `.txt.gz`. They are fetched by HTTP range GET at the tar offsets pinned in `plan.tsv`, after checking each member's 512-byte ustar header.
- Pins: the gzip trailer CRC32 and ISIZE (46,478,370) of every raster. NSIDC publishes no per-file checksums, so `download.sh` records the md5 and sha256 of every member in `member_checksums.tsv`.
- Download: 96,725,811 member bytes (96,733,119 bytes on disk including the checksum file).
- License: U.S. Government public domain (`LicenseRef-US-Government-Public-Domain`).
  - SNODAS is authored by NOAA NWS NOHRSC (17 U.S.C. 105). The NSIDC data page states "NOHRSC provides/creates the data, we just archive it".
  - The NWS disclaimer states that NWS information is "in the public domain, unless specifically noted otherwise" and "may be used without charge for any lawful purpose".
  - NSIDC requires citation ("As a condition of using these data, you must cite the use of this data set"). The manifest records the citation and DOI 10.7265/N5TB14TC.

## Shape and conversion

One natural record is one complete daily masked-CONUS grid:

- Size: 6935 columns x 3351 rows, i.e. 23,239,185 values and 46,478,370 bytes.
- Geometry: 30 arc-second WGS84, rows north to south, columns west to east.
- Source format: raw big-endian signed 2-byte integers. The header gives integer type, 2 bytes per pixel, slope 1, intercept 0, units Meters / 1000 and no-data -9999.

The conversion gunzips the member and writes the same values as little-endian int16. The values, the row-major order and the -9999 mask are unchanged. Nothing is cropped, resampled, tiled or concatenated.

The scope is 20 dates: 15 January and 15 February of every year from 2017 to 2026. All fall after the October 2013 masked-grid change, and all share the identical NOHRSC v1.1 header geometry. Between 2020 and 2021 only the header comment and product-code bookkeeping changed.

Snow depth, melt, sublimation, precipitation and temperature products in the same tars are never fetched.

## Accepted output

- Primary samples: 20 (one per date)
- Primary values: 464,783,700
- Primary bytes: 929,567,400 (under the 1 GB cap; the cap binds at about 21 untileable 46.5 MB grids)
- Sample size: 23,239,185 values (minimum = median = maximum)
- No-data -9999: 11,249,583 cells (48.41%) in every grid, with one distinct mask sha256 (`ff90695d9cc35240d5464aae56b880af5bf36f505d7f63f423a2276b311eb92c`). This is the native CONUS land mask and it is kept.
- Zero (no snow): 13.39%-39.17% per grid
- Positive SWE: 12.42%-38.20% per grid
- Distinct values per grid: 1,334-2,603
- Maximum valid value: 24,371 (2017-01-15) up to 32,767
- Cells at 32767: 86 in total, rising from 0 per grid through 2020-01-15 to 15 per grid in 2026. These are glacier cells at the int16 cap; they are kept and counted per sample.
- All 20 sample sha256 values are distinct.

## Judge checks

- `python3 tools/autocollect/gate.py staging/nsidc_snodas_masked_swe_i16`: PASS, with no warnings.
- `bash staging/nsidc_snodas_masked_swe_i16/verify.sh` (run by the judge): verify ok, 20 samples, 929,567,400 bytes.
  - It does an independent re-gunzip and a slice-assignment byte swap.
  - All 20 samples match the source byte for byte.
  - All index statistics, the mask hash, and the manifest count and size are recomputed.
- `build.sh` and `scripts/build_samples.py` read only local members; there are no network calls. No credentials appear anywhere in the recipe.
- Byte inspection with struct/array of 2017-01-15, 2021-02-15 and 2026-02-15:
  - Every grid starts with -9999 at the NW corner.
  - Positive values sit on a 1 mm lattice. The median is 14-53 mm, the 99th percentile 539-853 mm and the 99.9th percentile 839-1327 mm, so many values exceed 255 and the 16-bit width is honest.
  - The median horizontal neighbour difference among snow cells is 1-6 mm, a smooth geophysical field.
- Geolocation of the 32767 cells: row 722, col 358 maps to 46.854N, -121.746W (Mt Rainier), and row 491, col 350 to 48.779N, -121.813W (Mt Baker). This confirms the raster orientation and geometry.
- Near-duplicate check over four date pairs: only 0.6%-1.5% of cells with snow on either date are identical.
- Rights: the judge opened the NSIDC G02158 page (NOHRSC producer, NSIDC archive-only, citation condition) and the weather.gov disclaimer (public domain, any lawful use).
- Novelty checks:
  - `novelty.py --url` found no URL matches.
  - The terms SNODAS, NOHRSC, G02158 and "snow water equivalent" match only this candidate.
  - `--type snow_water_equivalent_grid` and `--instrument noaa_nohrsc_snodas` return 0. `--archive` returns only `noaa_ims_snow_ice_cover_u8`, a u8 class map.
  - Downstream `ghcn_wesd` (station SWE series) was found by hand. It means the card's "no SWE at any width" claim was overstated; the label is corrected to `new_source`.
- Fill: the driver listed no fill warnings. The constant 48.41% -9999 is the documented native land mask, matching the accepted `noaa_cdr_oisst_v21_sst_i16` static-land-fill precedent.
