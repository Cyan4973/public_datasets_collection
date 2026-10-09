# CMIP6 CESM2 historical daily precipitation flux (1940-1949), float32

This recipe collects all 3650 daily-mean global precipitation-flux fields (`pr`, kg m-2 s-1) from
the NCAR CESM2 coupled climate model's CMIP6 *historical* run, ensemble member `r1i1p1f1`, native
grid `gn` (192 x 288, 0.9 x 1.25 degree). They come from one pinned decade file of dataset version
`v20190401`. Each model day becomes one raw little-endian float32 sample of 55,296 values in
(lat, lon) row-major order. The values are exactly the stored model output.

## Source

- Bucket: `s3://esgf-world` (anonymous, us-east-2; AWS Registry of Open Data entry `cmip6`), the
  ESGF NetCDF mirror of CMIP6.
- Object: `CMIP6/CMIP/NCAR/CESM2/historical/r1i1p1f1/day/pr/gn/v20190401/pr_day_CESM2_historical_r1i1p1f1_gn_19400101-19491231.nc`
  - 663,390,696 bytes, S3 multipart ETag `accfa4a438ca6393474430698d9489dd-80` (80 parts of
    8 MiB). `download.sh` recomputes this ETag locally.
  - tracking_id `hdl:21.14100/c9b7ee29-8ac2-46d4-9e5c-b309b1ef0999`, written 2019-03-13 by
    netCDF 4.4.1.1 / HDF5 1.8.18.
- The same prefix holds 16 other decade files from 1850 to 2014. They are excluded on purpose:
  one file is a coherent, bounded scope (807 MB of output, under the 1 GB cap). Mixing in other
  decades, members or versions is avoided.

## License

The CESM2 CMIP6 output is **CC BY 4.0**. The official WCRP CMIP6 license table
(<https://wcrp-cmip.github.io/CMIP6_CVs/docs/CMIP6_source_id_licenses.html>) records it for
source_id CESM2 as "2019-02-18: initially published under CC BY-SA 4.0; 2022-06-16: relaxed to
CC BY 4.0". The PCMDI CMIP6 Terms of Use and the DataCite record of DOI 10.22033/ESGF/CMIP6.7627
also say CC BY 4.0. The file itself predates the relaxation and still embeds the original
CC BY-SA 4.0 notice. If you honor that notice conservatively, it adds a share-alike condition,
which this repository already accepts. `download.sh` fetches and checks the license table, the
Terms of Use page and the AWS registry entry on every run.

Citation: Danabasoglu, Gokhan (2019). NCAR CESM2 model output prepared for CMIP6 CMIP historical.
Version 20190401. Earth System Grid Federation. https://doi.org/10.22033/ESGF/CMIP6.7627

## Decode

The scripts are pure standard-library Python. `scripts/h5lite.py` is copied from the accepted
`geoschem_gc1470_fullchem_restart_species_f64` recipe. It reads the superblock (v0), the
version-2 object headers, dense attribute storage and the version-1 B-tree chunk index, and it
verifies lookup3 checksums on every metadata block it touches.

`pr` is stored as one chunk per day, shape (1, 192, 288), with the shuffle(4) + deflate pipeline.
Build inflates each chunk, reverses the byte shuffle, and writes the 221,184 bytes unchanged.

Validation checks:
- global attributes, including model, experiment, member, variable, grid and tracking_id
- datatype and layout
- `_FillValue` / `missing_value` = 1e20
- the noleap time axis (`time[i] = 707735 + i` days since 0001-01-01) and `time_bnds`
- the lat/lon coordinates
- chunk-index completeness

**Time stamp convention.** CESM2 stamps each daily mean at the *end* of its averaging interval:
`time_bnds[i] = (time[i] - 1, time[i])`. Sample names, and the CMOR file name, follow the time
coordinate, so `pr_day_19400101.bin` holds the mean over the model day ending 1940-01-01 00:00.
The index records both `time_days_since_0001_01_01_noleap` and `time_bnds`.

## Missing values and edge cases

- None of the 1e20 fill values are expected (the atmosphere grid has no mask). Any fill, NaN or
  Inf is fatal in both build and verify.
- Exact zeros (about 1% of cells in sampled days) and any tiny negative values the model writes
  are genuine model output and are kept verbatim. Each index row counts them.
- A field with fewer than 1000 distinct values or no positive value is rejected. Real fields have
  about 54,500 distinct values out of 55,296.

## Output

- `samples/cmip6_cesm2_historical_daily_precip_f32/pr_day_f32/pr_day_<YYYYMMDD>.bin`: 3650 files
  of 221,184 bytes each (807,321,600 bytes in total).
- `index/cmip6_cesm2_historical_daily_precip_f32/samples.jsonl`: the standard fields, plus
  `shape`, `axes`, `record_index`, time and bounds, `date_label`, `min`/`max` (from the stored
  float32), `zero_values`, `negative_values`, `distinct_values` and `sha256`.
- `filtered/cmip6_cesm2_historical_daily_precip_f32/build_summary.json`: totals and the embedded
  license attribute.

## Realized output (build of 2026-10-08)

- 3650 samples, 201,830,400 values, 807,321,600 bytes. The file's SHA-256
  `fce6d860a9e01b259b9534150392681c0766c6e904814737ad9ea657e36addba` is now pinned in `download.sh`.
- Exact zeros: 0.879% of all values (25 to 1579 per day, median 483).
- Negative values: none in the whole decade. Fill, NaN or Inf values: none.
- Distinct values per day: 53,459 to 55,151 (median 54,580).
- Value range: 0 to 6.117e-3 kg m-2 s-1.

## Verify

`verify.sh` reruns the synthetic self-test. It then resolves `pr` through the creation-order index
instead of the name index and re-decodes every chunk, byte-comparing it with the sample. On 11 spot
days it decodes again with an independent per-element unshuffle. It recomputes all statistics from
bit patterns and sorted values instead of the build's set-based path. It also rejects orphan or
missing files and duplicate fields, and checks the manifest's `sample_count` and
`total_size_bytes`.

## Notes

- A full decade is kept rather than every other day: the output fits under the cap, and thinning
  would only discard natural records that the download already pays for.
- Nearest local families: `weatherbench2_era5_pressure_level_fields_f32` (smooth reanalysis
  state fields: T/U/V/Z/Q/W on pressure levels; no precipitation), `open_meteo_hourly_precipitation`
  (tiny point series) and `dwd_radolan_rw_precip_i16` (regional radar, 16-bit words). This recipe
  is a free-running coupled climate model's global precipitation flux: sparse-ish, heavy-tailed,
  with positive values spanning more than 20 decades of magnitude. On two probed days the smallest
  positive value was about 6e-26, the median about 4e-6, the 99th percentile about 3e-4 and the
  maximum about 1.7e-3 kg m-2 s-1.
