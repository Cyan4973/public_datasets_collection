# Dataset State Report

Acceptance floor used by this report: at least `10000` primary values, at least `102400` primary bytes, median primary sample size at least `1000` values, and primary output at most `1000000000` bytes.

## `physionet_mitbih_annotation_codes_u8`

- status: `ok`
- reasons: `none`
- primary_samples: 48
- primary_values: 112647
- primary_bytes: 112647
- primary_value_count_range: 1519 / 2299 / 3400 min/median/max
- primary_size_range_bytes: 1519 / 2299 / 3400 min/median/max
- primary_size_distribution_bytes: 1519 / 1821.6 / 2061.5 / 2299 / 2650.2 / 3043.6 / 3400 min/p10/p25/median/p75/p90/max
- primary_same_size_fraction: 0.020833

| series_id | role | kind | width | samples | values | bytes | value distribution min/p10/p25/median/p75/p90/max | byte distribution min/p10/p25/median/p75/p90/max | same-size fraction | missing files |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| `mitbih_wfdb_annotation_type_u8` | primary | uint | 8 | 48 | 112647 | 112647 | 1519 / 1821.6 / 2061.5 / 2299 / 2650.2 / 3043.6 / 3400 | 1519 / 1821.6 / 2061.5 / 2299 / 2650.2 / 3043.6 / 3400 | 0.020833 | 0 |
