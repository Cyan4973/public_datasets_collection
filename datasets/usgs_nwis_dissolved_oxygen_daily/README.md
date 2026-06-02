# USGS NWIS Daily Dissolved Oxygen

This recipe collects a curated subset of USGS NWIS daily dissolved-oxygen
observations and converts selected numeric fields into raw numeric samples.

Selected scope:
- parameter code `00300` (dissolved oxygen)
- years `2021` through `2023`
- sites:
  - `07374000`
- one output sample per site per series

Series emitted by `build.sh`:
- `usgs_dissolved_oxygen_f64` (`float64`, little-endian)
- `obs_year_u16` (`uint16`, little-endian)
- `obs_month_u8` (`uint8`)
- `obs_day_u8` (`uint8`)
