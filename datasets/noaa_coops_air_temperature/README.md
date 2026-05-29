# NOAA CO-OPS Air Temperature

This recipe collects a curated subset of NOAA CO-OPS air-temperature
observations and converts them into raw numeric samples.

Selected scope:
- years `2022` through `2023`
- stations:
  - `9414290` (`san_francisco`)
  - `8518750` (`the_battery`)
  - `8443970` (`boston`)
- one output sample per station

Series emitted by `build.sh`:
- `air_temperature_f64` (`float64`, little-endian)

Notes:
- Source data comes from the NOAA CO-OPS datagetter API using product
  `air_temperature`.
- Downloads are chunked by fixed date ranges and stored as raw JSON.
- `download.sh` rejects NOAA API error payloads instead of caching them as
  successful inputs.
- `build.sh` preserves source timestamp order after deduplicating repeated
  timestamps across chunk boundaries.

Usage:

```sh
bash datasets/noaa_coops_air_temperature/download.sh
bash datasets/noaa_coops_air_temperature/build.sh
bash datasets/noaa_coops_air_temperature/verify.sh
```
