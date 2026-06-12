# FRED Federal Funds Monthly

This recipe collects the FRED `GDPC1` series and emits one sample per year.

Selected scope:
- FRED series: `GDPC1`
- years `2015` through `2024`
- one output sample per year per series

Series emitted by `build.sh`:
- `real_gdp_f32` (`float32`, little-endian)

Notes:
- Source data comes from the FRED graph CSV endpoint.
- `download.sh` validates the exact `DATE,GDPC1` header.
- Missing-value policy: blank values, `.` values, blank dates, malformed dates,
  and malformed numeric values are filtered.

Usage:

```sh
bash datasets/fred_real_gdp_quarterly/download.sh
bash datasets/fred_real_gdp_quarterly/build.sh
bash datasets/fred_real_gdp_quarterly/verify.sh
```
