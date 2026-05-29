# USGS NWIS Daily Water Temperature

This recipe collects a curated subset of USGS NWIS daily water-temperature
observations and converts selected numeric fields into raw numeric samples.

Selected scope:
- parameter code `00010` (water temperature)
- years `2021` through `2023`
- sites:
  - `01646500`
  - `07374000`
  - `09380000`
- one output sample per site per series

Series emitted by `build.sh`:
- `usgs_water_temperature_c_f64` (`float64`, little-endian)
- `obs_year_u16` (`uint16`, little-endian)
- `obs_month_u8` (`uint8`)
- `obs_day_u8` (`uint8`)
