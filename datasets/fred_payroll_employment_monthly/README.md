# FRED Payroll_Employment Monthly

This recipe collects the FRED `PAYEMS` series and emits one sample per year.

Selected scope:
- FRED series: `PAYEMS`
- years `2015` through `2024`
- one output sample per year per series

Series emitted by `build.sh`:
- `payroll_employment_f32` (`float32`, little-endian)

Notes:
- Source data comes from the FRED graph CSV endpoint.
- `download.sh` validates the exact `DATE,PAYEMS` header.
- Missing-value policy: blank values, `.` values, blank dates, malformed dates,
  and malformed numeric values are filtered.

Usage:

```sh
bash datasets/fred_payroll_employment_monthly/download.sh
bash datasets/fred_payroll_employment_monthly/build.sh
bash datasets/fred_payroll_employment_monthly/verify.sh
```
