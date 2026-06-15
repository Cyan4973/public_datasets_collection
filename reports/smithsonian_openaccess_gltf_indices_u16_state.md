# Dataset State Report

Acceptance floor used by this report: at least `10000` primary values, at least `102400` primary bytes, median primary sample size at least `1000` values, and primary output at most `1000000000` bytes.

## `smithsonian_openaccess_gltf_indices_u16`

- status: `ok`
- reasons: `none`
- primary_samples: 3
- primary_values: 899964
- primary_bytes: 1799928
- primary_value_count_range: 299976 / 299988 / 300000 min/median/max
- primary_size_range_bytes: 599952 / 599976 / 600000 min/median/max
- primary_size_distribution_bytes: 599952 / 599956.8 / 599964 / 599976 / 599988 / 599995.2 / 600000 min/p10/p25/median/p75/p90/max
- primary_same_size_fraction: 0.333333

| series_id | role | kind | width | samples | values | bytes | value distribution min/p10/p25/median/p75/p90/max | byte distribution min/p10/p25/median/p75/p90/max | same-size fraction | missing files |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| `mesh_index_accessors_u16` | primary | uint | 16 | 3 | 899964 | 1799928 | 299976 / 299978.4 / 299982 / 299988 / 299994 / 299997.6 / 300000 | 599952 / 599956.8 / 599964 / 599976 / 599988 / 599995.2 / 600000 | 0.333333 | 0 |

