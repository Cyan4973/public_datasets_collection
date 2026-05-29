# FRED Treasury 10Y Daily

This recipe collects the FRED `DGS10` series and emits one sample per year.

Selected scope:
- FRED series: `DGS10`
- years `2015` through `2024`
- one output sample per year per series

Series emitted by `build.sh`:
- `fred_value_f32` (`float32`, little-endian)
- `obs_month_u8` (`uint8`)
- `obs_day_u8` (`uint8`)

Notes:
- Source data comes from the FRED graph CSV endpoint.
- `download.sh` validates the exact `DATE,DGS10` header.
- Missing-value policy: blank values, `.` values, blank dates, malformed dates,
  and malformed numeric values are filtered.

Usage:

```sh
bash datasets/fred_treasury_10y_daily/download.sh
bash datasets/fred_treasury_10y_daily/build.sh
bash datasets/fred_treasury_10y_daily/verify.sh
```
