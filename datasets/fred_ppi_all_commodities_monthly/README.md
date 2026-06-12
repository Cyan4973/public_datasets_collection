# FRED Federal Funds Monthly

This recipe collects the FRED `PPIACO` series and emits one sample per year.

Selected scope:
- FRED series: `PPIACO`
- years `2015` through `2024`
- one output sample per year per series

Series emitted by `build.sh`:
- `ppi_all_commodities_f32` (`float32`, little-endian)

Notes:
- Source data comes from the FRED graph CSV endpoint.
- `download.sh` validates the exact `DATE,PPIACO` header.
- Missing-value policy: blank values, `.` values, blank dates, malformed dates,
  and malformed numeric values are filtered.

Usage:

```sh
bash datasets/fred_ppi_all_commodities_monthly/download.sh
bash datasets/fred_ppi_all_commodities_monthly/build.sh
bash datasets/fred_ppi_all_commodities_monthly/verify.sh
```
