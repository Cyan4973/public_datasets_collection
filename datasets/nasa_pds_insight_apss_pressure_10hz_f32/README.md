# nasa_pds_insight_apss_pressure_10hz_f32

Calibrated Mars surface atmospheric pressure (Pa) from the InSight lander's
APSS pressure sensor, sampled at 10 Hz. One raw little-endian float32 sample
per full-sol product, holding about 887,770 values in row order.

- Source: NASA PDS Atmospheres Node, bundle `urn:nasa:pds:insight_ps`,
  collection `data_calibrated`
  (<https://atmos.nmsu.edu/PDS/data/PDS4/InSight/ps_bundle/data_calibrated/>).
- License: CC0-1.0 under the NASA science data license for NASA-led mission
  data (<https://science.data.nasa.gov/about/license>). Cite the PDS bundle
  DOI 10.17189/1518939 and Banfield et al. 2019, SSR 215:4.
- Scope: 28 of the 496 full-sol 10 Hz `ps_calib_<SOL>_<VV>.csv` products
  (sols 169-1098), evenly spaced in sol order. Download about 2.54 GB; primary
  output about 99.4 MB.

## Files

| file | role |
|---|---|
| `files.tsv` | pinned inventory: sol dir, file, sol, byte size, PDS4-label MD5, records, header bytes, start/stop |
| `discover.sh`, `scripts/select_files.py` | how `files.tsv` was resolved (listings → labels → selection rule); not run by the pipeline |
| `download.sh` | resumable curl of the 28 CSVs; size + label-MD5 promotion; full semantic parse |
| `build.sh` → `scripts/apss_ps.py build` | PRESSURE → float32 samples, index, ingest stats |
| `verify.sh` → `scripts/verify_apss.py` | independent re-parse (csv module), byte compare, round-trip, index/manifest checks |
| `scripts/selftest_apss.py` | synthetic end-to-end and negative-path self-test (run by all three scripts) |

## Conversion

Field 6 `PRESSURE` (ASCII_Real `%10.4f`, pascal) is kept from rows where it is
non-empty and field 7 `PRESSURE_FREQUENCY` is exactly `10.0`. Each value is
parsed to the nearest float32. Every stored value must round back to the
identical 4-decimal source string, which holds below 1024 Pa because the
float32 half-ulp there is 3.05e-5 < 5e-5. Values are written in source row
order.

Not emitted:

- the timestamps (AOBT, SCLK, LMST, LTST, UTC);
- the cadence flag (`PRESSURE_FREQUENCY`);
- the 0.2 Hz sensor temperature (`PRESSURE_TEMP`), which is filled only every
  50th row.

## Missing values

Empty `PRESSURE` rows are dropped and counted per file. Non-10 Hz rows are
also dropped and counted; more than 1% of a file's rows is fatal. Malformed
decimals, out-of-range values (outside [100, 1500] Pa), round-trip failures,
field/record-count mismatches and size/MD5 mismatches are fatal. Counts appear
in `index/<id>/samples.jsonl` and `filtered/<id>/ingest_stats.json`.
Realized build: 0 blank and 0 non-10 Hz rows in all 28 files (every row kept);
24,857,573 values, 99,430,292 bytes, values 593.0-811.9 Pa.

## Homogeneity

The 28 samples all come from one sensor and one calibrated product line, in
one unit (Pa), on one 1e-4 Pa decimal lattice at one 10 Hz cadence, and each
covers one full sol. Partial-sol and 2 Hz/20 Hz products are excluded. Pressure
varies seasonally (realized 593-812 Pa) across the sampled sols. That is the same
regime at different levels, not a different scale.
