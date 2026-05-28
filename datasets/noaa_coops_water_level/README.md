# NOAA CO-OPS Water Level

This recipe collects a curated subset of NOAA CO-OPS verified water-level
observations and converts them into raw numeric samples.

Selected scope:
- 5 stations
- 6-minute verified water-level observations
- years `2022` and `2023`
- one output sample per station

Series emitted by `build.sh`:
- `water_level_f64` (`float64`, little-endian)

Selected stations:

```text
9414290 san_francisco
9447130 seattle
8518750 the_battery
8443970 boston
8724580 key_west
```

Station names:
- `9414290`: San Francisco, CA
- `9447130`: Seattle, WA
- `8518750`: The Battery, NY
- `8443970`: Boston, MA
- `8724580`: Key West, FL

Notes:
- Source data comes from the NOAA CO-OPS datagetter API.
- API parameters are fixed to verified water-level observations:
  - `product=water_level`
  - `datum=MLLW`
  - `units=metric`
  - `time_zone=gmt`
  - `interval=6`
  - `format=json`
- Downloads are chunked into deterministic 30-day API windows.
- `build.sh` sorts rows by NOAA UTC timestamp within each station.
- Only `data[].v` is emitted. Timestamps and NOAA quality/process flags are kept
  only for ordering and validation.
- Output values are IEEE-754 little-endian `float64` meters.

Usage:

```sh
bash datasets/noaa_coops_water_level/download.sh
bash datasets/noaa_coops_water_level/build.sh
bash datasets/noaa_coops_water_level/verify.sh
```

Local layout under `${DATA_DIR:-.data}`:
- `downloads/noaa_coops_water_level/download_plan.tsv`
- `downloads/noaa_coops_water_level/download_failures.tsv`
- `downloads/noaa_coops_water_level/<family>/*.json`
- `filtered/noaa_coops_water_level/station_stats.tsv`
- `index/noaa_coops_water_level/samples.jsonl`
- `logs/noaa_coops_water_level/download.latest.log`
- `logs/noaa_coops_water_level/build.latest.log`
- `logs/noaa_coops_water_level/verify.latest.log`
- `samples/noaa_coops_water_level/water_level_f64/<station_slug>.bin`

Logging:
- Every script writes timestamped logs under `${DATA_DIR:-.data}/logs/noaa_coops_water_level/`.
- Each script also refreshes a stable `*.latest.log` file for the most recent run.
- `download.sh` writes `download_failures.tsv` with one row per failed chunk fetch.

Sample index:
- `build.sh` writes `${DATA_DIR:-.data}/index/noaa_coops_water_level/samples.jsonl`.
- The index contains one JSON object per sample file with `dataset_id`,
  `series_id`, `sample_path`, `numeric_kind`, `bit_width`, `endianness`,
  `element_size_bytes`, `sample_size_bytes`, and `value_count`.
