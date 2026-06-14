# NOAA NDBC Historical Stdmet

This recipe collects a geographically diverse subset of NOAA NDBC historical
standard meteorological files spanning the Atlantic, Gulf of Mexico, Pacific,
and Hawaii, and converts selected numeric fields into raw numeric samples.

Selected scope:
- years `2019` through `2023`
- stations (39 total; station-years absent from the NDBC archive are skipped):
  - Atlantic Ocean: `41002`, `41004`, `41008`, `41009`, `41010`, `41025`, `41047`, `41048`, `44005`, `44008`, `44011`, `44013`, `44017`, `44025`, `44027`
  - Gulf of Mexico: `42001`, `42002`, `42019`, `42020`, `42036`
  - Pacific Ocean: `46002`, `46005`, `46006`, `46011`, `46012`, `46013`, `46014`, `46022`, `46025`, `46026`, `46028`, `46042`, `46047`, `46059`, `46069`
  - Hawaii / Pacific Islands: `51001`, `51002`, `51003`, `51004`
- elements:
  - `WDIR`
  - `WSPD`
  - `GST`
  - `WVHT`
  - `PRES`
  - `ATMP`
  - `WTMP`
- one output sample per retained station-element combination per series

Series emitted by `build.sh`:
- `ndbc_value_f64` (`float64`, little-endian)

Notes:
- Source data comes from NOAA NDBC historical standard meteorological archives.
- Downloads include one `.txt.gz` file per selected station-year.
- `build.sh` parses whitespace-delimited files, handles header and unit lines,
  preserves source row order, and keeps only rows with parseable selected
  elements and parseable date fields.
- Missing values represented as `MM` are skipped.
- Numeric values preserve parsed upstream magnitudes as IEEE-754 float64.
- Date component arrays are emitted only for retained `ndbc_value_f64` rows and
  therefore align 1:1.

Usage:

```sh
bash datasets/noaa_ndbc_stdmet_historical/download.sh
bash datasets/noaa_ndbc_stdmet_historical/build.sh
bash datasets/noaa_ndbc_stdmet_historical/verify.sh
```

Local layout under `${DATA_DIR:-.data}`:
- `downloads/noaa_ndbc_stdmet_historical/download_plan.tsv`
- `downloads/noaa_ndbc_stdmet_historical/download_failures.tsv`
- `downloads/noaa_ndbc_stdmet_historical/<station>h<year>.txt.gz`
- `downloads/noaa_ndbc_stdmet_historical/collection_checksums.sha256`
- `filtered/noaa_ndbc_stdmet_historical/station_element_year_stats.tsv`
- `index/noaa_ndbc_stdmet_historical/samples.jsonl`
- `logs/noaa_ndbc_stdmet_historical/download.latest.log`
- `logs/noaa_ndbc_stdmet_historical/build.latest.log`
- `logs/noaa_ndbc_stdmet_historical/verify.latest.log`
- `samples/noaa_ndbc_stdmet_historical/<series_id>/<station>_<element>.bin`

Logging:
- Every script writes timestamped logs under
  `${DATA_DIR:-.data}/logs/noaa_ndbc_stdmet_historical/`.
- Each script also refreshes a stable `*.latest.log` file for the most recent run.
- `download.sh` writes `download_failures.tsv` with one row per failed fetch.

Sample index:
- `build.sh` writes
  `${DATA_DIR:-.data}/index/noaa_ndbc_stdmet_historical/samples.jsonl`.
- Each row includes the standard sample index fields plus `station_id` and
  `element_id`.
