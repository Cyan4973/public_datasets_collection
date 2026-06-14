# NASA POWER Daily Humidity

This recipe collects a curated subset of NASA POWER daily point climate data
for humidity-related parameters and converts them into raw numeric samples.

Selected scope:
- years `2021` through `2023`
- locations: `san_francisco`, `phoenix`, `chicago`, `miami`, `anchorage`
- parameters:
  - `RH2M`
  - `T2MDEW`
  - `ALLSKY_SFC_SW_DWN`
- one output sample per location-parameter combination per series

Series emitted by `build.sh`:
- `power_value_f64` (`float64`, little-endian)
