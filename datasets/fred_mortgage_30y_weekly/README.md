# FRED Mortgage_30Y Weekly

This recipe collects the FRED `MORTGAGE30US` series and emits one sample per year.

Selected scope:
- FRED series: `MORTGAGE30US`
- years `2015` through `2024`
- one output sample per year per series

Series emitted by `build.sh`:
- `mortgage_30y_f32` (`float32`, little-endian)

Notes:
- Source data comes from the FRED graph CSV endpoint.
- `download.sh` validates the exact `DATE,MORTGAGE30US` header.
- Missing-value policy: blank values, `.` values, blank dates, malformed dates,
  and malformed numeric values are filtered.

Usage:

```sh
bash datasets/fred_mortgage_30y_weekly/download.sh
bash datasets/fred_mortgage_30y_weekly/build.sh
bash datasets/fred_mortgage_30y_weekly/verify.sh
```
