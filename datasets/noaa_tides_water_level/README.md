# NOAA Tides Water Level

NOAA CO-OPS coastal water-level time series for selected tide-gauge stations.

Selected scope:
- product: `water_level`
- datum: `MSL`
- units: metric
- time zone: GMT
- default date window: `2023-01-01` through `2024-12-31`
- 21 geographically distributed NOAA CO-OPS stations
- one sample per station per physical field

Series emitted by `build.sh`:
- `noaa_tides_level_f64`: observed water level in meters
- `noaa_tides_sigma_f64`: reported water-level sigma/uncertainty in meters

Verified local output from the default recipe:
- 42 homogeneous station samples
- 7,287,492 float64 values
- 58,299,936 primary sample bytes
- `noaa_tides_level_f64`: 21 samples, 3,643,746 values, median 175,440
- `noaa_tides_sigma_f64`: 21 samples, 3,643,746 values, median 175,440

The old calendar-derived `day`, `hour`, and `minute` series are intentionally
not emitted. They are not physical water-level measurements.

Default quality gates:
- `NOAA_TIDES_MIN_VALUES_PER_SAMPLE=100000`
- `NOAA_TIDES_VERIFY_MIN_VALUES_PER_SAMPLE=100000`
- `NOAA_TIDES_VERIFY_MIN_SAMPLES_PER_SERIES=15`
- `NOAA_TIDES_VERIFY_MIN_VALUES_PER_SERIES=1500000`

Usage:

```sh
bash datasets/noaa_tides_water_level/download.sh
bash datasets/noaa_tides_water_level/build.sh
bash datasets/noaa_tides_water_level/verify.sh
```

Tuning environment variables:
- `NOAA_TIDES_START_DATE`
- `NOAA_TIDES_END_DATE`
- `NOAA_TIDES_MIN_VALUES_PER_SAMPLE`
- `NOAA_TIDES_VERIFY_MIN_VALUES_PER_SAMPLE`
- `NOAA_TIDES_VERIFY_MIN_SAMPLES_PER_SERIES`
- `NOAA_TIDES_VERIFY_MIN_VALUES_PER_SERIES`

Local layout under `${DATA_DIR:-.data}`:
- `downloads/noaa_tides_water_level/download_plan.tsv`
- `downloads/noaa_tides_water_level/download_failures.tsv`
- `downloads/noaa_tides_water_level/station_<station>_<begin>_<end>.json`
- `filtered/noaa_tides_water_level/chunk_stats.tsv`
- `filtered/noaa_tides_water_level/ingest_stats.json`
- `index/noaa_tides_water_level/samples.jsonl`
- `samples/noaa_tides_water_level/<series_id>/station_<station>.bin`
- `logs/noaa_tides_water_level/*.latest.log`

No padding, synthesis, interpolation, or quantization is applied.
