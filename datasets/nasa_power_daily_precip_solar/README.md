# NASA POWER Daily_Precip_Solar

This recipe collects a curated subset of NASA POWER daily point wind
observations and converts selected numeric fields into raw numeric samples.

Selected scope:
- years `2021` through `2023`
- locations:
  - `san_francisco`
  - `phoenix`
  - `chicago`
  - `miami`
  - `anchorage`
- parameters:
  - `WS2M`
  - `WS10M`
  - `WS50M`
- one output sample per location-parameter pair per series

Series emitted by `build.sh`:
- `power_value_f64` (`float64`, little-endian)

Notes:
- Source data comes from the NASA POWER daily point API.
- `download.sh` validates that each JSON payload contains the expected
  parameter blocks before accepting it into cache.
- Missing-value policy: rows equal to the API `fill_value`, blank strings,
  `NaN`, malformed date keys, and malformed numeric values are filtered.

Usage:

```sh
bash datasets/nasa_power_daily_precip_solar/download.sh
bash datasets/nasa_power_daily_precip_solar/build.sh
bash datasets/nasa_power_daily_precip_solar/verify.sh
```
