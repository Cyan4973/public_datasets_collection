# USGS NWIS Daily Specific Conductance

This recipe collects a curated subset of USGS NWIS daily specific-conductance
observations and converts selected numeric fields into raw numeric samples.

Selected scope:
- parameter code `00095` (specific conductance)
- years `2021` through `2023`
- sites:
  - `07374000`
  - `09380000`
- one output sample per site per series

Series emitted by `build.sh`:
- `usgs_specific_conductance_f64` (`float64`, little-endian)
- `obs_year_u16` (`uint16`, little-endian)
- `obs_month_u8` (`uint8`)
- `obs_day_u8` (`uint8`)
