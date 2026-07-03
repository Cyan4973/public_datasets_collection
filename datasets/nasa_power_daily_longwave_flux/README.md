# NASA POWER Daily Longwave Flux

This recipe collects a curated subset of NASA POWER daily point longwave
radiation flux data and converts selected numeric fields into raw numeric
samples.

Selected scope:
- years `1988` through `2024`
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
  - `ALLSKY_SFC_LW_DWN`
  - `CLRSKY_SFC_LW_DWN`
- one output sample per location in each parameter-specific series

Series emitted by `build.sh`:
- `nasa_power_longwave_allsky_lw_down_f64` (`float64`, little-endian)
- `nasa_power_longwave_clrsky_lw_down_f64` (`float64`, little-endian)

Notes:
- Source data comes from the NASA POWER daily point API.
- `download.sh` validates that each JSON payload contains the expected
  parameter blocks before accepting it into cache.
- Missing-value policy: rows equal to the API `fill_value`, blank strings,
  `NaN`, malformed date keys, and malformed numeric values are filtered.
- Each series is homogeneous: one longwave-radiation parameter, one natural
  daily time-series sample per location.
- Temperature is intentionally excluded; it belongs in a temperature-specific
  recipe rather than this longwave-flux recipe.
- The default window can be overridden with
  `NASA_POWER_DAILY_LONGWAVE_FLUX_START_YEAR` and
  `NASA_POWER_DAILY_LONGWAVE_FLUX_END_YEAR`.

Usage:

```sh
bash datasets/nasa_power_daily_longwave_flux/download.sh
bash datasets/nasa_power_daily_longwave_flux/build.sh
bash datasets/nasa_power_daily_longwave_flux/verify.sh
```
