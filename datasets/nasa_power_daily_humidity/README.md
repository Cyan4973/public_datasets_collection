# NASA POWER Daily Humidity

This recipe collects a curated subset of NASA POWER daily point climate data
for humidity-related parameters and converts them into raw numeric samples.

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
  - `RH2M`
  - `T2MDEW`
- one output sample per location in each parameter-specific series

Series emitted by `build.sh`:
- `nasa_power_humidity_rh2m_f64` (`float64`, little-endian)
- `nasa_power_humidity_t2mdew_f64` (`float64`, little-endian)

Notes:
- Source data comes from the NASA POWER daily point API.
- `download.sh` validates that each JSON payload contains the expected
  parameter blocks before accepting it into cache.
- Missing-value policy: rows equal to the API `fill_value`, blank strings,
  `NaN`, malformed date keys, and malformed numeric values are filtered.
- Each series is homogeneous: one humidity-related parameter, one natural daily
  time-series sample per location.
- Solar radiation is intentionally excluded; it belongs in a solar-specific
  recipe rather than this humidity recipe.
- The default window can be overridden with `NASA_POWER_DAILY_HUMIDITY_START_YEAR`
  and `NASA_POWER_DAILY_HUMIDITY_END_YEAR`.
