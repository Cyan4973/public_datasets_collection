# Dataset State Report

Acceptance floor used by this report: at least `10000` primary values, at least `102400` primary bytes, median primary sample size at least `1000` values, and primary output at most `1000000000` bytes.

## `librispeech_dev_clean_i16`

- status: `ok`
- reasons: `none`
- primary_samples: 2703
- primary_values: 310337932
- primary_bytes: 620675864
- primary_value_count_range: 23120 / 94720 / 522320 min/median/max
- primary_size_range_bytes: 46240 / 189440 / 1044640 min/median/max
- primary_size_distribution_bytes: 46240 / 87232 / 120320 / 189440 / 296560 / 426528.0 / 1044640 min/p10/p25/median/p75/p90/max
- primary_same_size_fraction: 0.002590

| series_id | role | kind | width | samples | values | bytes | value distribution min/p10/p25/median/p75/p90/max | byte distribution min/p10/p25/median/p75/p90/max | same-size fraction | missing files |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| `librispeech_dev_clean_pcm16` | primary | int | 16 | 2703 | 310337932 | 620675864 | 23120 / 43616 / 60160 / 94720 / 148280 / 213264.0 / 522320 | 46240 / 87232 / 120320 / 189440 / 296560 / 426528.0 / 1044640 | 0.002590 | 0 |

