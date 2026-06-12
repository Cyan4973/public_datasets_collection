# ECB FX EUR Daily Matrix

This staged recipe replaces the fragmented `ecb_fx_*_eur_daily` standalones
with one homogeneous ECB FX family recipe.

Selected scope:
- ECB daily exchange-rate series
- `19` currency pairs against `EUR`
- years `2015` through `2024`
- one output sample per year per currency pair

Series emitted by `build.sh`:
- one `float32` little-endian value series per currency pair:
  - `ecb_fx_aud_eur_value_f32`
  - `ecb_fx_cad_eur_value_f32`
  - `ecb_fx_chf_eur_value_f32`
  - `ecb_fx_czk_eur_value_f32`
  - `ecb_fx_dkk_eur_value_f32`
  - `ecb_fx_gbp_eur_value_f32`
  - `ecb_fx_hkd_eur_value_f32`
  - `ecb_fx_huf_eur_value_f32`
  - `ecb_fx_jpy_eur_value_f32`
  - `ecb_fx_krw_eur_value_f32`
  - `ecb_fx_mxn_eur_value_f32`
  - `ecb_fx_nok_eur_value_f32`
  - `ecb_fx_nzd_eur_value_f32`
  - `ecb_fx_pln_eur_value_f32`
  - `ecb_fx_ron_eur_value_f32`
  - `ecb_fx_sek_eur_value_f32`
  - `ecb_fx_sgd_eur_value_f32`
  - `ecb_fx_try_eur_value_f32`
  - `ecb_fx_usd_eur_value_f32`

Notes:
- This is a homogeneous family recipe:
  - same source
  - same cadence
  - same unit semantics
  - same material type
- `download.sh` validates that each CSV contains `TIME_PERIOD` and `OBS_VALUE`.
- Missing-value policy: blank values, blank dates, malformed dates, and
  malformed numeric values are filtered.
- This recipe is staged only. Promote it into `datasets/` only after the
  current `download.sh` has been user-run and the recipe has then passed local
  `build.sh` and `verify.sh`.

Usage:

```sh
bash staging/ecb_fx_eur_daily_matrix/download.sh
bash staging/ecb_fx_eur_daily_matrix/build.sh
bash staging/ecb_fx_eur_daily_matrix/verify.sh
```
