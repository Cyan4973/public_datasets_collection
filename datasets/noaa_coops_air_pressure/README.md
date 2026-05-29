# NOAA CO-OPS Air Pressure

This recipe collects a curated subset of NOAA CO-OPS air-pressure observations
and converts them into raw numeric samples.

Selected scope:
- years `2022` through `2023`
- stations: `san_francisco`, `the_battery`, `boston`
- one output sample per station

Series emitted by `build.sh`:
- `air_pressure_f64` (`float64`, little-endian)

Notes:
- Source data comes from the NOAA CO-OPS datagetter API using product
  `air_pressure`.
- `download.sh` rejects NOAA API error payloads instead of caching them as
  successful inputs.
