# NOAA CO-OPS Water Temperature

This recipe collects a curated subset of NOAA CO-OPS water-temperature
observations and converts them into raw numeric samples.

Selected scope:
- years `2022` through `2023`
- stations: `san_francisco`, `the_battery`
- one output sample per station

Series emitted by `build.sh`:
- `water_temperature_f64` (`float64`, little-endian)

Notes:
- Source data comes from the NOAA CO-OPS datagetter API using product
  `water_temperature`.
- `download.sh` rejects NOAA API error payloads instead of caching them as
  successful inputs.
