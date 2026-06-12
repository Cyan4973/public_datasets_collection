# FRED Unemployment Rate Monthly

This recipe collects the FRED `UNRATE` series and emits one sample per year.

Selected scope:
- FRED series: `UNRATE`
- years `2015` through `2024`
- one output sample per year per series

Series emitted by `build.sh`:
- `unemployment_rate_f32` (`float32`, little-endian)

Notes:
- Source data comes from the FRED graph CSV endpoint.
- `download.sh` validates the exact `DATE,UNRATE` header.
- Missing-value policy: blank values, `.` values, blank dates, malformed dates,
  and malformed numeric values are filtered.

Usage:

```sh
bash datasets/fred_unemployment_rate_monthly/download.sh
bash datasets/fred_unemployment_rate_monthly/build.sh
bash datasets/fred_unemployment_rate_monthly/verify.sh
```
