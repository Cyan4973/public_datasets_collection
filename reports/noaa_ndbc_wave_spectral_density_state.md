# Dataset State Report

Acceptance floor used by this report: at least `10000` primary values, at least `102400` primary bytes, median primary sample size at least `1000` values, and primary output at most `1000000000` bytes.

## `noaa_ndbc_wave_spectral_density_f64`

- status: `ok`
- reasons: `none`
- primary_samples: 24
- primary_values: 11719309
- primary_bytes: 93754472
- primary_value_count_range: 106690 / 427159.5 / 819586 min/median/max
- primary_size_range_bytes: 853520 / 3417276 / 6556688 min/median/max
- primary_size_distribution_bytes: 853520 / 1658949.6 / 3217902 / 3417276 / 5115856 / 6540708 / 6556688 min/p10/p25/median/p75/p90/max
- primary_same_size_fraction: 0.041667

| series_id | role | kind | width | samples | values | bytes | value distribution min/p10/p25/median/p75/p90/max | byte distribution min/p10/p25/median/p75/p90/max | same-size fraction | missing files |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| `wave_spectral_density` | primary | float | 64 | 24 | 11719309 | 93754472 | 106690 / 207368.7 / 402237.8 / 427159.5 / 639482 / 817588.5 / 819586 | 853520 / 1658949.6 / 3217902 / 3417276 / 5115856 / 6540708 / 6556688 | 0.041667 | 0 |

