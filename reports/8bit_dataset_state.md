# Dataset State Report

Acceptance floor used by this report: at least `10000` primary values, at least `102400` primary bytes, and median primary sample size at least `1000` values.

## `medmnist_pathmnist_images_u8`

- status: `ok`
- reasons: `none`
- primary_samples: 107180
- primary_values: 252087360
- primary_bytes: 252087360
- primary_value_count_range: 2352 / 2352 / 2352 min/median/max
- primary_size_range_bytes: 2352 / 2352 / 2352 min/median/max

| series_id | role | kind | width | samples | values | bytes | value range min/median/max | byte range min/median/max | missing files |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| `pathmnist_images` | primary | uint | 8 | 107180 | 252087360 | 252087360 | 2352 / 2352 / 2352 | 2352 / 2352 / 2352 | 0 |
