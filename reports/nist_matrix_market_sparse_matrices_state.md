# Dataset State Report

Acceptance floor used by this report: at least `10000` primary values, at least `102400` primary bytes, median primary sample size at least `1000` values, and primary output at most `1000000000` bytes.

## `nist_matrix_market_sparse_matrices`

- status: `ok`
- reasons: `none`
- primary_samples: 57
- primary_values: 2300385
- primary_bytes: 12268720
- primary_value_count_range: 1288 / 15100 / 219812 min/median/max
- primary_size_range_bytes: 5152 / 71428 / 1758496 min/median/max
- primary_size_distribution_bytes: 5152 / 8330.4 / 16560 / 71428 / 261040 / 611975.2 / 1758496 min/p10/p25/median/p75/p90/max
- primary_same_size_fraction: 0.035088

| series_id | role | kind | width | samples | values | bytes | value distribution min/p10/p25/median/p75/p90/max | byte distribution min/p10/p25/median/p75/p90/max | same-size fraction | missing files |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| `col_index_u32` | primary | uint | 32 | 19 | 766795 | 3067180 | 1288 / 1874 / 3987.5 / 15100 / 51912.5 / 94915.0 / 219812 | 5152 / 7496 / 15950 / 60400 / 207650 / 379660.0 / 879248 | 0.052632 | 0 |
| `entry_value_f64` | primary | float | 64 | 19 | 766795 | 6134360 | 1288 / 1874 / 3987.5 / 15100 / 51912.5 / 94915.0 / 219812 | 10304 / 14992 / 31900 / 120800 / 415300 / 759320.0 / 1758496 | 0.052632 | 0 |
| `row_index_u32` | primary | uint | 32 | 19 | 766795 | 3067180 | 1288 / 1874 / 3987.5 / 15100 / 51912.5 / 94915.0 / 219812 | 5152 / 7496 / 15950 / 60400 / 207650 / 379660.0 / 879248 | 0.052632 | 0 |

