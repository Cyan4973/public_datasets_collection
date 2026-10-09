# Cloudnet Lindenberg CHM15k raw attenuated backscatter (beta_raw), float32

Native float32 ceilometer backscatter profiles from the ACTRIS Cloudnet data
portal. The source is the single DWD Lufft CHM15k ceilometer (serial
CHM100110, Cloudnet instrument `cdf99c53-6bd0-4146-be2a-604cf1164c30`) at
the Lindenberg Meteorological Observatory (MOL-RAO, Germany). Each sample is
the complete `beta_raw` matrix of one daily Cloudnet `lidar` product file:
time × 1535 range gates, one profile every 15 s, gates 9.99 m apart from
9.99 m to 15.33 km, in units of sr-1 m-1. The values are exactly as stored
by CloudnetPy 1.75.0, as little-endian IEEE binary32 in time-major order.

- **Scope:** 24 days, the 1st and 15th of each month of 2024. Every file
  is errorLevel `pass` with coverage ≥ 0.99, and all 24 have
  cloudnetpy 1.75.0 and cloudnet-processing 2.54.18.
- **Realized volume:** 919,628,874 download bytes; 24 samples with
  212,137,000 float32 values (848,548,000 bytes). 23 days have
  5760 × 1535; 2024-03-01 has 5720 × 1535 (one 625 s gap). The median
  sample is 8,841,600 values. No fill, NaN or out-of-range values occur.
- **Storage:** full days are chunked (2880, 768), i.e. 2 × 2 chunks with
  a padded edge chunk along range (2024-03-01: (2860, 768)), deflate
  level 4 after shuffle.
- **License:** CC BY 4.0. docs.cloudnet.fmi.fi, section "License": "Cloudnet
  data is licensed under a Creative Commons Attribution 4.0 international
  licence." Keep the Cloudnet/ACTRIS/DWD attribution and the per-file PIDs.

## Files

| file | role |
| --- | --- |
| `sources.tsv` | the 24 pinned files: date, uuid, filename, size, sha256, cloudnetpy version (itself pinned by SHA-256 in `scripts/chm15k.py`) |
| `discover.sh` | documents how `sources.tsv` was selected from the files API (authoring only) |
| `download.sh` | per-uuid files-API check, then whole-file fetch + size/sha256/decode validation |
| `build.sh` | decodes `beta_raw` and writes samples + `samples.jsonl` (local files only) |
| `verify.sh` | independent re-decode (different chunk walk, inflate and unshuffle code) + byte comparison + stats/index/manifest checks |
| `scripts/h5lite.py` | pure-stdlib HDF5 reader (copied from the accepted `noaa_stofs2d_glo_adcirc_station_water_level_f64` recipe) |
| `scripts/chm15k.py` | product validation, decode, build, verify |
| `scripts/selftest_chm15k.py` | synthetic HDF5 round trip and negative cases |

## Download notes

The Cloudnet download endpoint ignores HTTP `Range`: a range GET returns
the whole file with status 200. `download.sh` therefore:

- never resumes (no `curl -C -`);
- uses the small `GET /api/files/<uuid>` record as its liveness and pin
  check;
- fetches each file whole into a fresh `.part`, which it accepts only after
  the size, SHA-256 and full-decode checks pass;
- retries a failed file up to 4 times;
- keeps files that already passed validation on re-runs.

If Cloudnet reprocesses a day, the new version gets a new uuid. The pinned
uuid stays addressable, but `check-meta` fails if its record no longer
matches the pin, for example if it is tombstoned.

## Material

`beta_raw` is the range-corrected attenuated backscatter delivered by the
CHM15k and scaled by CloudnetPy's calibration factor. It is
background-subtracted, so clear-air gates are signed noise of about ±1e-5
(roughly 40% of values are negative). Aerosol layers, cloud bases and
precipitation give positive returns up to about 1e-3.

The file also contains `beta` (the same field after SNR screening and
masking) and `beta_smooth`. Both derive from `beta_raw` and are not emitted.
The co-located CL61d and DA10 instruments, and CHM15k units at other sites,
are excluded so the family stays one instrument and one processing chain.

## Missing values

Values are stored and emitted unchanged.

- **Gaps:** missing profiles are simply absent from the time axis, so the
  matrix has fewer rows. 5700 to 5800 rows are required (5760 nominal), and the longest
  gap is recorded per sample.
- **Fill:** the netCDF default fill value 9.969209968386869e36 (bits
  `0x7CF00000`, the variable's `_FillValue`) is kept in place if present. It
  is counted per sample and excluded from the recorded min/max/mean/std. A
  day with more than 1% fill is fatal.
- **Invalid values:** NaN, infinity, or any non-fill |v| > 1 is fatal.

## Checks

- Every chunk must be present exactly once, aligned, with filter mask 0,
  and must inflate to the full chunk size.
- The range axis must be byte-identical across all 24 files.
- The time step must have a median of 15 s.
- Each sample must have at least 100k distinct values in a stride-8
  subsample, a negative-value fraction between 5% and 95%, nonzero
  variance, and differing first and last profiles.
- No two samples may be identical.
