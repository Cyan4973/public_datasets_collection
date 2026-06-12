# FRED SP500 Daily

This recipe collects the FRED `SP500` series and emits one sample per year.

Selected scope:
- FRED series: `SP500`
- years `2015` through `2024`
- one output sample per year per series

Series emitted by `build.sh`:
- `fred_value_f32` (`float32`, little-endian)

Notes:
- Source data comes from the FRED graph CSV endpoint.
- `download.sh` validates the exact `DATE,SP500` header.
- Missing-value policy: blank values, `.` values, blank dates, malformed dates,
  and malformed numeric values are filtered.

Usage:

```sh
bash datasets/fred_sp500_daily/download.sh
bash datasets/fred_sp500_daily/build.sh
bash datasets/fred_sp500_daily/verify.sh
```
