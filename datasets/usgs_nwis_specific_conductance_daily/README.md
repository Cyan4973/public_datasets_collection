# USGS NWIS Daily Specific Conductance

This recipe collects USGS NWIS daily specific-conductance observations and
converts selected numeric fields into raw numeric samples.

Selected scope:
- parameter code `00095` (specific conductance)
- years `2021` through `2024`
- broad deterministic nationwide probe aiming for up to `50` usable stream-site samples
- candidate sites are derived deterministically from fixed active-stream site
  inventory queries across a fixed nationwide state list
- `download.sh` keeps candidate sites whose site inventory row has a non-empty,
  non-all-`N` `instruments_cd`, round-robins those candidates by state, and
  keeps the usable sites it finds, capped at `50`
- one output sample per selected site per series

Series emitted by `build.sh`:
- `usgs_specific_conductance_f64` (`float64`, little-endian)

Current local build contents:
- `29` sites with usable specific-conductance samples
- one sample per site
- median sample length `1406` values
