# Dataset State Report

Acceptance floor used by this report: at least `10000` primary values, at least `102400` primary bytes, median primary sample size at least `1000` values, and primary output at most `1000000000` bytes.

## `gbif_occurrence_2024_coordinate_sample`

- status: `ok`
- reasons: `none`
- primary_samples: 8
- primary_values: 95952
- primary_bytes: 527736
- primary_value_count_range: 11994 / 11994 / 11994 min/median/max
- primary_size_range_bytes: 47976 / 47976 / 95952 min/median/max
- primary_size_distribution_bytes: 47976 / 47976 / 47976 / 47976 / 95952 / 95952 / 95952 min/p10/p25/median/p75/p90/max
- primary_same_size_fraction: 0.625000

| series_id | role | kind | width | samples | values | bytes | value distribution min/p10/p25/median/p75/p90/max | byte distribution min/p10/p25/median/p75/p90/max | same-size fraction | missing files |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| `gbif_class_key_u32` | primary | uint | 32 | 1 | 11994 | 47976 | 11994 / 11994 / 11994 / 11994 / 11994 / 11994 / 11994 | 47976 / 47976 / 47976 / 47976 / 47976 / 47976 / 47976 | 1.000000 | 0 |
| `gbif_decimal_latitude_f64` | primary | float | 64 | 1 | 11994 | 95952 | 11994 / 11994 / 11994 / 11994 / 11994 / 11994 / 11994 | 95952 / 95952 / 95952 / 95952 / 95952 / 95952 / 95952 | 1.000000 | 0 |
| `gbif_decimal_longitude_f64` | primary | float | 64 | 1 | 11994 | 95952 | 11994 / 11994 / 11994 / 11994 / 11994 / 11994 / 11994 | 95952 / 95952 / 95952 / 95952 / 95952 / 95952 / 95952 | 1.000000 | 0 |
| `gbif_kingdom_key_u32` | primary | uint | 32 | 1 | 11994 | 47976 | 11994 / 11994 / 11994 / 11994 / 11994 / 11994 / 11994 | 47976 / 47976 / 47976 / 47976 / 47976 / 47976 / 47976 | 1.000000 | 0 |
| `gbif_occurrence_key_u64` | primary | uint | 64 | 1 | 11994 | 95952 | 11994 / 11994 / 11994 / 11994 / 11994 / 11994 / 11994 | 95952 / 95952 / 95952 / 95952 / 95952 / 95952 / 95952 | 1.000000 | 0 |
| `gbif_order_key_u32` | primary | uint | 32 | 1 | 11994 | 47976 | 11994 / 11994 / 11994 / 11994 / 11994 / 11994 / 11994 | 47976 / 47976 / 47976 / 47976 / 47976 / 47976 / 47976 | 1.000000 | 0 |
| `gbif_phylum_key_u32` | primary | uint | 32 | 1 | 11994 | 47976 | 11994 / 11994 / 11994 / 11994 / 11994 / 11994 / 11994 | 47976 / 47976 / 47976 / 47976 / 47976 / 47976 / 47976 | 1.000000 | 0 |
| `gbif_taxon_key_u32` | primary | uint | 32 | 1 | 11994 | 47976 | 11994 / 11994 / 11994 / 11994 / 11994 / 11994 / 11994 | 47976 / 47976 / 47976 / 47976 / 47976 / 47976 / 47976 | 1.000000 | 0 |

