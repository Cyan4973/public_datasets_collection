# Dataset State Report

Acceptance floor used by this report: at least `10000` primary values, at least `102400` primary bytes, median primary sample size at least `1000` values, and primary output at most `1000000000` bytes.

## `taginfo_keys_all`

- status: `ok`
- reasons: `none`
- primary_samples: 8
- primary_values: 800000
- primary_bytes: 5100000
- primary_value_count_range: 100000 / 100000 / 100000 min/median/max
- primary_size_range_bytes: 100000 / 800000 / 800000 min/median/max
- primary_size_distribution_bytes: 100000 / 170000 / 650000 / 800000 / 800000 / 800000 / 800000 min/p10/p25/median/p75/p90/max
- primary_same_size_fraction: 0.750000

| series_id | role | kind | width | samples | values | bytes | value distribution min/p10/p25/median/p75/p90/max | byte distribution min/p10/p25/median/p75/p90/max | same-size fraction | missing files |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| `taginfo_count_all` | primary | uint | 64 | 1 | 100000 | 800000 | 100000 / 100000 / 100000 / 100000 / 100000 / 100000 / 100000 | 800000 / 800000 / 800000 / 800000 / 800000 / 800000 / 800000 | 1.000000 | 0 |
| `taginfo_count_nodes` | primary | uint | 64 | 1 | 100000 | 800000 | 100000 / 100000 / 100000 / 100000 / 100000 / 100000 / 100000 | 800000 / 800000 / 800000 / 800000 / 800000 / 800000 / 800000 | 1.000000 | 0 |
| `taginfo_count_relations` | primary | uint | 64 | 1 | 100000 | 800000 | 100000 / 100000 / 100000 / 100000 / 100000 / 100000 / 100000 | 800000 / 800000 / 800000 / 800000 / 800000 / 800000 / 800000 | 1.000000 | 0 |
| `taginfo_count_ways` | primary | uint | 64 | 1 | 100000 | 800000 | 100000 / 100000 / 100000 / 100000 / 100000 / 100000 / 100000 | 800000 / 800000 / 800000 / 800000 / 800000 / 800000 / 800000 | 1.000000 | 0 |
| `taginfo_in_wiki` | primary | uint | 8 | 1 | 100000 | 100000 | 100000 / 100000 / 100000 / 100000 / 100000 / 100000 / 100000 | 100000 / 100000 / 100000 / 100000 / 100000 / 100000 / 100000 | 1.000000 | 0 |
| `taginfo_projects` | primary | uint | 16 | 1 | 100000 | 200000 | 100000 / 100000 / 100000 / 100000 / 100000 / 100000 / 100000 | 200000 / 200000 / 200000 / 200000 / 200000 / 200000 / 200000 | 1.000000 | 0 |
| `taginfo_users_all` | primary | uint | 64 | 1 | 100000 | 800000 | 100000 / 100000 / 100000 / 100000 / 100000 / 100000 / 100000 | 800000 / 800000 / 800000 / 800000 / 800000 / 800000 / 800000 | 1.000000 | 0 |
| `taginfo_values_all` | primary | uint | 64 | 1 | 100000 | 800000 | 100000 / 100000 / 100000 / 100000 / 100000 / 100000 / 100000 | 800000 / 800000 / 800000 / 800000 / 800000 / 800000 / 800000 | 1.000000 | 0 |
