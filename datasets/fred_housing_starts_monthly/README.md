# FRED Housing_Starts Monthly

This recipe collects the FRED `HOUST` series and emits one sample per year.

Selected scope:
- FRED series: `HOUST`
- years `2015` through `2024`
- one output sample per year per series

Series emitted by `build.sh`:
- `housing_starts_f32` (`float32`, little-endian)
- `obs_month_u8` (`uint8`)
- `obs_day_u8` (`uint8`)

Notes:
- Source data comes from the FRED graph CSV endpoint.
- `download.sh` validates the exact `DATE,HOUST` header.
- Missing-value policy: blank values, `.` values, blank dates, malformed dates,
  and malformed numeric values are filtered.

Usage:

```sh
bash datasets/fred_housing_starts_monthly/download.sh
bash datasets/fred_housing_starts_monthly/build.sh
bash datasets/fred_housing_starts_monthly/verify.sh
```
