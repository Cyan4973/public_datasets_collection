# FRED Federal Funds Monthly

This recipe collects the FRED `DCOILWTICO` series and emits one sample per year.

Selected scope:
- FRED series: `DCOILWTICO`
- years `2015` through `2024`
- one output sample per year per series

Series emitted by `build.sh`:
- `wti_crude_f32` (`float32`, little-endian)

Notes:
- Source data comes from the FRED graph CSV endpoint.
- `download.sh` validates the exact `DATE,DCOILWTICO` header.
- Missing-value policy: blank values, `.` values, blank dates, malformed dates,
  and malformed numeric values are filtered.

Usage:

```sh
bash datasets/fred_wti_crude_daily/download.sh
bash datasets/fred_wti_crude_daily/build.sh
bash datasets/fred_wti_crude_daily/verify.sh
```
