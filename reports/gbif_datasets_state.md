# Dataset State Report

Acceptance floor used by this report: at least `10000` primary values, at least `102400` primary bytes, median primary sample size at least `1000` values, and primary output at most `1000000000` bytes.

## `gbif_datasets`

- status: `ok`
- reasons: `none`
- primary_samples: 3
- primary_values: 300000
- primary_bytes: 1200000
- primary_value_count_range: 100000 / 100000 / 100000 min/median/max
- primary_size_range_bytes: 200000 / 200000 / 800000 min/median/max
- primary_size_distribution_bytes: 200000 / 200000 / 200000 / 200000 / 500000 / 680000 / 800000 min/p10/p25/median/p75/p90/max
- primary_same_size_fraction: 0.666667

| series_id | role | kind | width | samples | values | bytes | value distribution min/p10/p25/median/p75/p90/max | byte distribution min/p10/p25/median/p75/p90/max | same-size fraction | missing files |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| `gbif_decade_count_u16` | primary | uint | 16 | 1 | 100000 | 200000 | 100000 / 100000 / 100000 / 100000 / 100000 / 100000 / 100000 | 200000 / 200000 / 200000 / 200000 / 200000 / 200000 / 200000 | 1.000000 | 0 |
| `gbif_keyword_count_u16` | primary | uint | 16 | 1 | 100000 | 200000 | 100000 / 100000 / 100000 / 100000 / 100000 / 100000 / 100000 | 200000 / 200000 / 200000 / 200000 / 200000 / 200000 / 200000 | 1.000000 | 0 |
| `gbif_record_count_u64` | primary | uint | 64 | 1 | 100000 | 800000 | 100000 / 100000 / 100000 / 100000 / 100000 / 100000 / 100000 | 800000 / 800000 / 800000 / 800000 / 800000 / 800000 / 800000 | 1.000000 | 0 |
