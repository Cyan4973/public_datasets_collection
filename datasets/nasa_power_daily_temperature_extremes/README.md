# NASA POWER Daily Temperature Extremes

This recipe collects a curated subset of NASA POWER daily point temperature
observations and converts selected numeric fields into raw numeric samples.

Selected scope:
- years `1981` through `2024`
- locations:
  - `san_francisco`
  - `phoenix`
  - `chicago`
  - `miami`
  - `anchorage`
  - `fairbanks`
  - `honolulu`
  - `denver`
  - `new_orleans`
  - `san_juan`
  - `seattle`
  - `boston`
  - `atlanta`
  - `dallas`
  - `minneapolis`
  - `las_vegas`
  - `albuquerque`
  - `portland`
  - `billings`
  - `fargo`
- parameters:
  - `T2M`
  - `T2M_MAX`
  - `T2M_MIN`
- one output sample per location in each parameter-specific series

Series emitted by `build.sh`:
- `nasa_power_temperature_t2m_f64` (`float64`, little-endian)
- `nasa_power_temperature_t2m_max_f64` (`float64`, little-endian)
- `nasa_power_temperature_t2m_min_f64` (`float64`, little-endian)

Notes:
- Source data comes from the NASA POWER daily point API.
- `download.sh` validates that each JSON payload contains the expected
  parameter blocks before accepting it into cache.
- Missing-value policy: rows equal to the API `fill_value`, blank strings,
  `NaN`, malformed date keys, and malformed numeric values are filtered.
- Each series is homogeneous: one temperature parameter, one natural daily
  time-series sample per location.
- The default window can be overridden with
  `NASA_POWER_DAILY_TEMPERATURE_EXTREMES_START_YEAR` and
  `NASA_POWER_DAILY_TEMPERATURE_EXTREMES_END_YEAR`.

Usage:

```sh
bash datasets/nasa_power_daily_temperature_extremes/download.sh
bash datasets/nasa_power_daily_temperature_extremes/build.sh
bash datasets/nasa_power_daily_temperature_extremes/verify.sh
```
