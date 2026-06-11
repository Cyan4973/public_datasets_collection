# NOAA GHCN Daily TAVG By Station

This recipe collects a curated subset of NOAA GHCN Daily station archives and
retains average temperature (`TAVG`) observations as raw numeric samples.

Selected scope:
- years `1763` through `2026`
- stations: a fixed, deterministic spread of 83 US airport (USW/ASOS)
  stations, which report the wind / gust / sunshine / average-temperature
  elements that COOP stations do not; see `download.sh` for the exact pinned list
- one output sample per station that reports the element, per series

Series emitted by `build.sh`:
- `ghcn_value_i16` (`int16`, little-endian)

Notes:
- Source data comes from NOAA NCEI GHCN Daily by-station archives.
- `download.sh` validates both the station metadata file and each gzip station
  archive before accepting them into cache.
- Missing-value policy: rows with non-blank quality flags, malformed dates, or
  out-of-range numeric values are filtered.
