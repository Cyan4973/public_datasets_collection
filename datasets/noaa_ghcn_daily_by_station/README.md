# NOAA GHCN Daily By Station

This recipe collects a curated subset of NOAA GHCN Daily station files and
converts selected climate elements into raw numeric samples.

Selected scope:
- years `2010` through `2023`
- stations:
  - `USW00094728`
  - `USW00014922`
  - `USW00094846`
  - `USW00014739`
  - `USW00023062`
  - `USW00025339`
- elements:
  - `TMAX`
  - `TMIN`
  - `PRCP`
  - `SNOW`
  - `SNWD`
- one output sample per retained station-element combination per series

Series emitted by `build.sh`:
- `ghcn_value_i16` (`int16`, little-endian)
- `obs_year_u16` (`uint16`, little-endian)
- `obs_month_u8` (`uint8`)
- `obs_day_u8` (`uint8`)

Notes:
- Source data comes from NOAA NCEI GHCN Daily by-station CSV archives.
- Downloads include one `.csv.gz` file per selected station plus
  `ghcnd-stations.txt` for metadata.
- `build.sh` keeps only rows whose element is in the selected set, year is in
  `2010-2023`, quality flag is blank, and value/date fields parse cleanly.
- `build.sh` preserves source row order within each station file.
- The numeric values preserve native GHCN integer units:
  - `TMAX` and `TMIN`: tenths of degrees Celsius
  - `PRCP`: tenths of millimeters
  - `SNOW`: millimeters
  - `SNWD`: millimeters
- `obs_year_u16`, `obs_month_u8`, and `obs_day_u8` are emitted only for rows
  retained in `ghcn_value_i16`, so those arrays align 1:1.

Usage:

```sh
bash datasets/noaa_ghcn_daily_by_station/download.sh
bash datasets/noaa_ghcn_daily_by_station/build.sh
bash datasets/noaa_ghcn_daily_by_station/verify.sh
```

Local layout under `${DATA_DIR:-.data}`:
- `downloads/noaa_ghcn_daily_by_station/download_plan.tsv`
- `downloads/noaa_ghcn_daily_by_station/download_failures.tsv`
- `downloads/noaa_ghcn_daily_by_station/ghcnd-stations.txt`
- `downloads/noaa_ghcn_daily_by_station/<station>.csv.gz`
- `downloads/noaa_ghcn_daily_by_station/collection_checksums.sha256`
- `filtered/noaa_ghcn_daily_by_station/station_element_year_stats.tsv`
- `index/noaa_ghcn_daily_by_station/samples.jsonl`
- `logs/noaa_ghcn_daily_by_station/download.latest.log`
- `logs/noaa_ghcn_daily_by_station/build.latest.log`
- `logs/noaa_ghcn_daily_by_station/verify.latest.log`
- `samples/noaa_ghcn_daily_by_station/<series_id>/<station>_<element>.bin`

Logging:
- Every script writes timestamped logs under
  `${DATA_DIR:-.data}/logs/noaa_ghcn_daily_by_station/`.
- Each script also refreshes a stable `*.latest.log` file for the most recent run.
- `download.sh` writes `download_failures.tsv` with one row per failed fetch.

Sample index:
- `build.sh` writes
  `${DATA_DIR:-.data}/index/noaa_ghcn_daily_by_station/samples.jsonl`.
- Each row includes the standard sample index fields plus `station_id` and
  `element_id`.
