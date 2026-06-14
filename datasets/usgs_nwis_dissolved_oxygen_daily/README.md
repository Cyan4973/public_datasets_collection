# USGS NWIS Daily Dissolved Oxygen

This recipe collects USGS NWIS daily dissolved-oxygen observations and converts
selected numeric fields into raw numeric samples.

Selected scope:
- parameter code `00300` (dissolved oxygen)
- years `2021` through `2024`
- broad deterministic nationwide probe aiming for up to `50` usable stream-site samples
- candidate sites are derived deterministically from fixed active-stream site
  inventory queries across a fixed nationwide state list
- `download.sh` keeps candidate sites whose site inventory row has a non-empty,
  non-all-`N` `instruments_cd`, round-robins those candidates by state, and
  keeps the usable sites it finds, capped at `50`
- one output sample per selected site with available data

Series emitted by `build.sh`:
- `usgs_dissolved_oxygen_f64` (`float64`, little-endian)

Current local build contents:
- `15` sites with usable dissolved-oxygen samples
- one sample per site with available data
- median sample length `1343` values
