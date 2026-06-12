# FRED Federal Funds Monthly

This recipe collects the FRED `UNEMPLOY` series and emits one sample per year.

Selected scope:
- FRED series: `UNEMPLOY`
- years `2015` through `2024`
- one output sample per year per series

Series emitted by `build.sh`:
- `unemployment_level_f32` (`float32`, little-endian)

Notes:
- Source data comes from the FRED graph CSV endpoint.
- `download.sh` validates the exact `DATE,UNEMPLOY` header.
- Missing-value policy: blank values, `.` values, blank dates, malformed dates,
  and malformed numeric values are filtered.

Usage:

```sh
bash datasets/fred_unemployment_level_monthly/download.sh
bash datasets/fred_unemployment_level_monthly/build.sh
bash datasets/fred_unemployment_level_monthly/verify.sh
```
