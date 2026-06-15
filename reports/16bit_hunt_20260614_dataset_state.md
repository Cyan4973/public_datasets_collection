# 16-bit Hunt Dataset State

Acceptance floor used by this report: at least `10000` primary values, at least `102400` primary bytes, median primary sample size at least `1000` values, and primary output at most `1000000000` bytes.

| dataset_id | status | primary samples | primary bytes | min / p10 / p25 / median / p75 / p90 / max sample bytes | unique sizes | same-size fraction | reasons |
|---|---:|---:|---:|---|---:|---:|---|
| `librispeech_dev_clean_i16` | `ok` | 2703 | 620675864 | 46240 / 87232 / 120320 / 189440 / 296560 / 426528.0 / 1044640 | 1680 | 0.002590 | none |
| `skadi_srtm_bay_area_hgt_i16` | `ok` | 1 | 25934402 | 25934402 / 25934402 / 25934402 / 25934402 / 25934402 / 25934402 / 25934402 | 1 | 1.000000 | none |

`librispeech_dev_clean_i16` has been promoted to `datasets/`; focused
material report: `reports/librispeech_dev_clean_i16_state.md`.
