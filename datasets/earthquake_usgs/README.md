# USGS Earthquake Catalog

This recipe collects a curated subset of the USGS Earthquake Catalog and
converts selected numeric fields into raw numeric samples.

Selected scope:
- magnitude `>= 4.0`
- years `2014` through `2023`
- one output sample per year per series

Series emitted by `build.sh`:
- `eq_depth_f64` (`float64`, little-endian)
- `eq_mag_f64` (`float64`, little-endian)
- `eq_gap_f64` (`float64`, little-endian)
- `eq_dmin_f64` (`float64`, little-endian)
- `eq_nst_u16` (`uint16`, little-endian)

Notes:
- Source data comes from the USGS FDSN event query API in CSV format.
- Downloads are chunked by calendar year with fixed UTC query windows.
- `build.sh` preserves source row order within each year.
- `depth`, `mag`, `gap`, and `dmin` are emitted as parsed float64 values.
- `nst` is emitted as uint16 when present; rows with missing `nst` are skipped
  for the `eq_nst_u16` series only.
- No padding, synthesis, interpolation, or quantization is applied.

Usage:

```sh
bash datasets/earthquake_usgs/download.sh
bash datasets/earthquake_usgs/build.sh
bash datasets/earthquake_usgs/verify.sh
```

Local layout under `${DATA_DIR:-.data}`:
- `downloads/earthquake_usgs/download_plan.tsv`
- `downloads/earthquake_usgs/download_failures.tsv`
- `downloads/earthquake_usgs/quakes_<year>.csv`
- `filtered/earthquake_usgs/year_series_stats.tsv`
- `index/earthquake_usgs/samples.jsonl`
- `logs/earthquake_usgs/download.latest.log`
- `logs/earthquake_usgs/build.latest.log`
- `logs/earthquake_usgs/verify.latest.log`
- `samples/earthquake_usgs/<series_id>/<year>.bin`

Logging:
- Every script writes timestamped logs under `${DATA_DIR:-.data}/logs/earthquake_usgs/`.
- Each script also refreshes a stable `*.latest.log` file for the most recent run.
- `download.sh` writes `download_failures.tsv` with one row per failed yearly fetch.
- The yearly query windows are `YYYY-01-01T00:00:00` through
  `YYYY-12-31T23:59:59.999` UTC.

Sample index:
- `build.sh` writes `${DATA_DIR:-.data}/index/earthquake_usgs/samples.jsonl`.
- The index contains one JSON object per sample file with `dataset_id`,
  `series_id`, `sample_path`, `numeric_kind`, `bit_width`, `endianness`,
  `element_size_bytes`, `sample_size_bytes`, and `value_count`.
