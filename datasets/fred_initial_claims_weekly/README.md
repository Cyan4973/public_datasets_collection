# FRED Initial_Claims Weekly

This recipe collects the FRED `ICSA` series and emits one sample per year.

Selected scope:
- FRED series: `ICSA`
- years `2015` through `2024`
- one output sample per year per series

Series emitted by `build.sh`:
- `initial_claims_f32` (`float32`, little-endian)

Notes:
- Source data comes from the FRED graph CSV endpoint.
- `download.sh` validates the exact `DATE,ICSA` header.
- Missing-value policy: blank values, `.` values, blank dates, malformed dates,
  and malformed numeric values are filtered.

Usage:

```sh
bash datasets/fred_initial_claims_weekly/download.sh
bash datasets/fred_initial_claims_weekly/build.sh
bash datasets/fred_initial_claims_weekly/verify.sh
```
