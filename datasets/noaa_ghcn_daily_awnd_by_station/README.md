# NOAA GHCN Daily AWND By Station

This recipe collects a curated subset of NOAA GHCN Daily station archives and
retains average wind speed (`AWND`) observations as raw numeric samples.

Selected scope:
- years `1763` through `2026`
- stations: a fixed, deterministic set of 59 US long-record stations —
  the original 6 first-order airport stations plus a spread of US HCN
  reference-network stations; see `download.sh` for the exact pinned list
- one output sample per station that reports the element, per series

Series emitted by `build.sh`:
- `ghcn_value_i16` (`int16`, little-endian)

Notes:
- Source data comes from NOAA NCEI GHCN Daily by-station archives.
- `download.sh` validates both the station metadata file and each gzip station
  archive before accepting them into cache.
- Missing-value policy: rows with non-blank quality flags, malformed dates, or
  out-of-range numeric values are filtered.
