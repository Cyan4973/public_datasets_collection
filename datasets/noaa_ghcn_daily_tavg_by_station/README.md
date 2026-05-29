# NOAA GHCN Daily TAVG By Station

This recipe collects a curated subset of NOAA GHCN Daily station archives and
retains average temperature (`TAVG`) observations as raw numeric samples.

Selected scope:
- years `2010` through `2023`
- stations:
  - `USW00094728`
  - `USW00014922`
  - `USW00094846`
  - `USW00014739`
  - `USW00023062`
  - `USW00025339`
- one output sample per station per series

Series emitted by `build.sh`:
- `ghcn_value_i16` (`int16`, little-endian)
- `obs_year_u16` (`uint16`, little-endian)
- `obs_month_u8` (`uint8`)
- `obs_day_u8` (`uint8`)

Notes:
- Source data comes from NOAA NCEI GHCN Daily by-station archives.
- `download.sh` validates both the station metadata file and each gzip station
  archive before accepting them into cache.
- Missing-value policy: rows with non-blank quality flags, malformed dates, or
  out-of-range numeric values are filtered.
