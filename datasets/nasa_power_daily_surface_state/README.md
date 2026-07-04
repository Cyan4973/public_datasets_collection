# NASA POWER Daily Surface State

This recipe collects a curated subset of NASA POWER daily point surface-state
data and converts selected numeric fields into raw numeric samples.

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
  - `PS`
  - `QV2M`
  - `T2MWET`
- one output sample per location in each parameter-specific series

Series emitted by `build.sh`:
- `nasa_power_surface_pressure_ps_f64` (`float64`, little-endian)
- `nasa_power_surface_specific_humidity_qv2m_f64` (`float64`, little-endian)
- `nasa_power_surface_wetbulb_t2mwet_f64` (`float64`, little-endian)

Notes:
- Source data comes from the NASA POWER daily point API.
- `download.sh` validates that each JSON payload contains the expected
  parameter blocks before accepting it into cache.
- Missing-value policy: rows equal to the API `fill_value`, blank strings,
  `NaN`, malformed date keys, and malformed numeric values are filtered.
- Each series is homogeneous: one surface-state parameter, one natural daily
  time-series sample per location.
- The default window can be overridden with
  `NASA_POWER_DAILY_SURFACE_STATE_START_YEAR` and
  `NASA_POWER_DAILY_SURFACE_STATE_END_YEAR`.

Usage:

```sh
bash datasets/nasa_power_daily_surface_state/download.sh
bash datasets/nasa_power_daily_surface_state/build.sh
bash datasets/nasa_power_daily_surface_state/verify.sh
```
