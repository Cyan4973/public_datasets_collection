# Dataset State Report

Acceptance floor used by this report: at least `10000` primary values, at least `102400` primary bytes, median primary sample size at least `1000` values, and primary output at most `1000000000` bytes.

## `dataone_solr`

- status: `ok`
- reasons: `none`
- primary_samples: 7
- primary_values: 602719
- primary_bytes: 2805438
- primary_value_count_range: 2719 / 100000 / 100000 min/median/max
- primary_size_range_bytes: 5438 / 400000 / 800000 min/median/max
- primary_size_distribution_bytes: 5438 / 122175.2 / 200000 / 400000 / 600000 / 800000 / 800000 min/p10/p25/median/p75/p90/max
- primary_same_size_fraction: 0.285714

| series_id | role | kind | width | samples | values | bytes | value distribution min/p10/p25/median/p75/p90/max | byte distribution min/p10/p25/median/p75/p90/max | same-size fraction | missing files |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| `dataone_date_modified` | primary | uint | 64 | 1 | 100000 | 800000 | 100000 / 100000 / 100000 / 100000 / 100000 / 100000 / 100000 | 800000 / 800000 / 800000 / 800000 / 800000 / 800000 / 800000 | 1.000000 | 0 |
| `dataone_date_uploaded` | primary | uint | 32 | 1 | 100000 | 400000 | 100000 / 100000 / 100000 / 100000 / 100000 / 100000 / 100000 | 400000 / 400000 / 400000 / 400000 / 400000 / 400000 / 400000 | 1.000000 | 0 |
| `dataone_modified_year` | primary | uint | 16 | 1 | 100000 | 200000 | 100000 / 100000 / 100000 / 100000 / 100000 / 100000 / 100000 | 200000 / 200000 / 200000 / 200000 / 200000 / 200000 / 200000 | 1.000000 | 0 |
| `dataone_number_replicas` | primary | uint | 16 | 1 | 2719 | 5438 | 2719 / 2719 / 2719 / 2719 / 2719 / 2719 / 2719 | 5438 / 5438 / 5438 / 5438 / 5438 / 5438 / 5438 | 1.000000 | 0 |
| `dataone_size` | primary | uint | 64 | 1 | 100000 | 800000 | 100000 / 100000 / 100000 / 100000 / 100000 / 100000 / 100000 | 800000 / 800000 / 800000 / 800000 / 800000 / 800000 / 800000 | 1.000000 | 0 |
| `dataone_update_date` | primary | uint | 32 | 1 | 100000 | 400000 | 100000 / 100000 / 100000 / 100000 / 100000 / 100000 / 100000 | 400000 / 400000 / 400000 / 400000 / 400000 / 400000 / 400000 | 1.000000 | 0 |
| `dataone_uploaded_year` | primary | uint | 16 | 1 | 100000 | 200000 | 100000 / 100000 / 100000 / 100000 / 100000 / 100000 / 100000 | 200000 / 200000 / 200000 / 200000 / 200000 / 200000 / 200000 | 1.000000 | 0 |
