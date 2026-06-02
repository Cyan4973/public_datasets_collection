# Open-Meteo Hourly Apparent_Temperature

This recipe collects a curated subset of Open-Meteo archive hourly
temperature observations and converts them into raw numeric samples.

Selected scope:
- years `2022` through `2023`
- locations:
  - `san_francisco`
  - `phoenix`
  - `chicago`
  - `miami`
  - `anchorage`
- hourly variable:
  - `apparent_temperature`
- one output sample per location per series

Series emitted by `build.sh`:
- `open_meteo_value_f32` (`float32`, little-endian)
- `obs_year_u16` (`uint16`, little-endian)
- `obs_month_u8` (`uint8`)
- `obs_day_u8` (`uint8`)
- `obs_hour_u8` (`uint8`)

Notes:
- Source data comes from the Open-Meteo archive API.
- `download.sh` validates that each JSON payload contains `hourly.time` and
  `hourly.apparent_temperature` with matching lengths before accepting it into cache.
- Missing-value policy: blank or null values, malformed timestamps, and
  malformed numeric values are filtered.

Usage:

```sh
bash datasets/open_meteo_hourly_apparent_temperature/download.sh
bash datasets/open_meteo_hourly_apparent_temperature/build.sh
bash datasets/open_meteo_hourly_apparent_temperature/verify.sh
```
