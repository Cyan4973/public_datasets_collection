# NASA POWER Daily Precipitation

This recipe collects a curated subset of NASA POWER daily point precipitation
data and converts the corrected precipitation field into raw numeric samples.

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
  - `PRECTOTCORR`
- one output sample per location

Series emitted by `build.sh`:
- `nasa_power_precip_prectotcorr_f64` (`float64`, little-endian)

Notes:
- Source data comes from the NASA POWER daily point API.
- `download.sh` validates that each JSON payload contains the expected
  parameter block before accepting it into cache.
- Missing-value policy: rows equal to the API `fill_value`, blank strings,
  `NaN`, malformed date keys, and malformed numeric values are filtered.
- The series is homogeneous: corrected daily total precipitation, one natural
  daily time-series sample per location.
- Temperature fields are intentionally excluded; they belong in
  temperature-specific recipes rather than this precipitation recipe.
- The default window can be overridden with
  `NASA_POWER_DAILY_PRECIP_TEMPERATURE_START_YEAR` and
  `NASA_POWER_DAILY_PRECIP_TEMPERATURE_END_YEAR`.

Usage:

```sh
bash datasets/nasa_power_daily_precip_temperature/download.sh
bash datasets/nasa_power_daily_precip_temperature/build.sh
bash datasets/nasa_power_daily_precip_temperature/verify.sh
```
