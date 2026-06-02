# FRED Treasury 2Y Monthly

This recipe collects the FRED `DGS2` series and emits one sample per year.

Selected scope:
- FRED series: `DGS2`
- years `2015` through `2024`
- one output sample per year per series

Series emitted by `build.sh`:
- `fred_value_f32` (`float32`, little-endian)
- `obs_month_u8` (`uint8`)
- `obs_day_u8` (`uint8`)

Notes:
- Source data comes from the FRED graph CSV endpoint.
- `download.sh` validates the exact `DATE,DGS2` header.
- Missing-value policy: blank values, `.` values, blank dates, malformed dates,
  and malformed numeric values are filtered.

Usage:

```sh
bash datasets/fred_treasury_2y_daily/download.sh
bash datasets/fred_treasury_2y_daily/build.sh
bash datasets/fred_treasury_2y_daily/verify.sh
```
