# Dataset State Report

Acceptance floor used by this report: at least `10000` primary values, at least `102400` primary bytes, median primary sample size at least `1000` values, and primary output at most `1000000000` bytes.

## `bbbc038_nuclei_masks_u8`

- status: `ok`
- reasons: `none`
- primary_samples: 3468
- primary_values: 949747588
- primary_bytes: 949747588
- primary_value_count_range: 65536 / 129600 / 1048576 min/median/max
- primary_size_range_bytes: 65536 / 129600 / 1048576 min/median/max
- primary_size_distribution_bytes: 65536 / 65536 / 81920 / 129600 / 361920 / 361920 / 1048576 min/p10/p25/median/p75/p90/max
- primary_same_size_fraction: 0.407728

| series_id | role | kind | width | samples | values | bytes | value distribution min/p10/p25/median/p75/p90/max | byte distribution min/p10/p25/median/p75/p90/max | same-size fraction | missing files |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| `bbbc038_nuclei_mask_u8` | primary | uint | 8 | 3468 | 949747588 | 949747588 | 65536 / 65536 / 81920 / 129600 / 361920 / 361920 / 1048576 | 65536 / 65536 / 81920 / 129600 / 361920 / 361920 / 1048576 | 0.407728 | 0 |
