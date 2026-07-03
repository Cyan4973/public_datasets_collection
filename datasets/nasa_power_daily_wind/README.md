# NASA POWER Daily Wind

This recipe collects a curated subset of NASA POWER daily point wind
observations and converts selected numeric fields into raw numeric samples.

Selected scope:
- years `1984` through `2024`
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
- parameters:
  - `WS2M`
  - `WS10M`
  - `WS50M`
- one output sample per location in each parameter-specific series

Series emitted by `build.sh`:
- `nasa_power_wind_ws2m_f64` (`float64`, little-endian)
- `nasa_power_wind_ws10m_f64` (`float64`, little-endian)
- `nasa_power_wind_ws50m_f64` (`float64`, little-endian)

Notes:
- Source data comes from the NASA POWER daily point API.
- `download.sh` validates that each JSON payload contains the expected
  parameter blocks before accepting it into cache.
- Missing-value policy: rows equal to the API `fill_value`, blank strings,
  `NaN`, malformed date keys, and malformed numeric values are filtered.
- Each series is homogeneous: one wind-speed height parameter, one natural
  daily time-series sample per location.
- The default window can be overridden with `NASA_POWER_DAILY_WIND_START_YEAR`
  and `NASA_POWER_DAILY_WIND_END_YEAR`.

Usage:

```sh
bash datasets/nasa_power_daily_wind/download.sh
bash datasets/nasa_power_daily_wind/build.sh
bash datasets/nasa_power_daily_wind/verify.sh
```
