# NASA POWER Daily Climate

This recipe collects a curated subset of NASA POWER daily point climate data
and converts selected numeric fields into raw numeric samples.

Selected scope:
- years `2021` through `2023`
- locations:
  - `san_francisco`
  - `phoenix`
  - `chicago`
  - `miami`
  - `anchorage`
- parameters:
  - `T2M`
  - `PRECTOTCORR`
  - `WS2M`
- one output sample per retained location-parameter combination per series

Series emitted by `build.sh`:
- `power_value_f64` (`float64`, little-endian)

Notes:
- Source data comes from the NASA POWER daily point JSON API.
- Downloads include one JSON file per selected location-year.
- `build.sh` preserves source day order within each location-year response and
  concatenates years in ascending order for each location-parameter sample.
- Missing values equal to the API fill value are skipped.
- `power_value_f64` preserves parsed upstream magnitudes as IEEE-754 float64.
- Date component arrays are emitted only for retained `power_value_f64` rows and
  therefore align 1:1.

Usage:

```sh
bash datasets/nasa_power_daily_climate/download.sh
bash datasets/nasa_power_daily_climate/build.sh
bash datasets/nasa_power_daily_climate/verify.sh
```

Local layout under `${DATA_DIR:-.data}`:
- `downloads/nasa_power_daily_climate/download_plan.tsv`
- `downloads/nasa_power_daily_climate/download_failures.tsv`
- `downloads/nasa_power_daily_climate/<location>_<year>.json`
- `downloads/nasa_power_daily_climate/collection_checksums.sha256`
- `filtered/nasa_power_daily_climate/location_parameter_year_stats.tsv`
- `index/nasa_power_daily_climate/samples.jsonl`
- `logs/nasa_power_daily_climate/download.latest.log`
- `logs/nasa_power_daily_climate/build.latest.log`
- `logs/nasa_power_daily_climate/verify.latest.log`
- `samples/nasa_power_daily_climate/<series_id>/<location>_<parameter>.bin`

Logging:
- Every script writes timestamped logs under
  `${DATA_DIR:-.data}/logs/nasa_power_daily_climate/`.
- Each script also refreshes a stable `*.latest.log` file for the most recent run.
- `download.sh` writes `download_failures.tsv` with one row per failed fetch.

Sample index:
- `build.sh` writes
  `${DATA_DIR:-.data}/index/nasa_power_daily_climate/samples.jsonl`.
- Each row includes the standard sample index fields plus `location_id` and
  `parameter_id`.
