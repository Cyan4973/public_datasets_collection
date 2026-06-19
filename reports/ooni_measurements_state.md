# Dataset State Report

Acceptance floor used by this report: at least `10000` primary values, at least `102400` primary bytes, median primary sample size at least `1000` values, and primary output at most `1000000000` bytes.

## `ooni_measurements`

- status: `ok`
- reasons: `none`
- primary_samples: 3
- primary_values: 60000
- primary_bytes: 240000
- primary_value_count_range: 20000 / 20000 / 20000 min/median/max
- primary_size_range_bytes: 80000 / 80000 / 80000 min/median/max
- primary_size_distribution_bytes: 80000 / 80000 / 80000 / 80000 / 80000 / 80000 / 80000 min/p10/p25/median/p75/p90/max
- primary_same_size_fraction: 1.000000

| series_id | role | kind | width | samples | values | bytes | value distribution min/p10/p25/median/p75/p90/max | byte distribution min/p10/p25/median/p75/p90/max | same-size fraction | missing files |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| `ooni_blocking_general_score_f32` | primary | float | 32 | 1 | 20000 | 80000 | 20000 / 20000 / 20000 / 20000 / 20000 / 20000 / 20000 | 80000 / 80000 / 80000 / 80000 / 80000 / 80000 / 80000 | 1.000000 | 0 |
| `ooni_measurement_unix_u32` | primary | uint | 32 | 1 | 20000 | 80000 | 20000 / 20000 / 20000 / 20000 / 20000 / 20000 / 20000 | 80000 / 80000 / 80000 / 80000 / 80000 / 80000 / 80000 | 1.000000 | 0 |
| `ooni_probe_asn_u32` | primary | uint | 32 | 1 | 20000 | 80000 | 20000 / 20000 / 20000 / 20000 / 20000 / 20000 / 20000 | 80000 / 80000 / 80000 / 80000 / 80000 / 80000 / 80000 | 1.000000 | 0 |

