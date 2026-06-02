# ECB FX SGD/EUR Daily

This recipe collects the ECB daily SGD/EUR exchange-rate series and emits one
sample per year.

Selected scope:
- ECB series key: `D.SGD.EUR.SP00.A`
- years `2015` through `2024`
- one output sample per year per series

Series emitted by `build.sh`:
- `ecb_fx_value_f32` (`float32`, little-endian)
- `obs_month_u8` (`uint8`)
- `obs_day_u8` (`uint8`)

Notes:
- Source data comes from the ECB Data Portal CSV API.
- `download.sh` validates that the CSV contains `TIME_PERIOD` and `OBS_VALUE`.
- Missing-value policy: blank values, blank dates, malformed dates, and
  malformed numeric values are filtered.

Usage:

```sh
bash datasets/ecb_fx_sgd_eur_daily/download.sh
bash datasets/ecb_fx_sgd_eur_daily/build.sh
bash datasets/ecb_fx_sgd_eur_daily/verify.sh
```
