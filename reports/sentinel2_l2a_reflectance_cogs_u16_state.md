# Dataset State Report

Acceptance floor used by this report: at least `10000` primary values, at least `102400` primary bytes, median primary sample size at least `1000` values, and primary output at most `1000000000` bytes.

## `sentinel2_l2a_reflectance_cogs_u16`

- status: `ok`
- reasons: `none`
- primary_samples: 6
- primary_values: 308098800
- primary_bytes: 616197600
- primary_value_count_range: 3348900 / 30140100 / 120560400 min/median/max
- primary_size_range_bytes: 6697800 / 60280200 / 241120800 min/median/max
- primary_size_distribution_bytes: 6697800 / 6697800 / 20093400 / 60280200 / 195910650 / 241120800 / 241120800 min/p10/p25/median/p75/p90/max
- primary_same_size_fraction: 0.333333

| series_id | role | kind | width | samples | values | bytes | value distribution min/p10/p25/median/p75/p90/max | byte distribution min/p10/p25/median/p75/p90/max | same-size fraction | missing files |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| `sentinel2_l2a_reflectance_pixels_u16` | primary | uint | 16 | 6 | 308098800 | 616197600 | 3348900 / 3348900 / 10046700 / 30140100 / 97955325 / 120560400 / 120560400 | 6697800 / 6697800 / 20093400 / 60280200 / 195910650 / 241120800 / 241120800 | 0.333333 | 0 |
