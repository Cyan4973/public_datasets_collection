# Dataset State Report

Acceptance floor used by this report: at least `10000` primary values, at least `102400` primary bytes, median primary sample size at least `1000` values, and primary output at most `1000000000` bytes.

## `google_fonts_ofl_ttf_u8`

- status: `ok`
- reasons: `none`
- primary_samples: 122
- primary_values: 33876096
- primary_bytes: 33876096
- primary_value_count_range: 19596 / 205386 / 5772308 min/median/max
- primary_size_range_bytes: 19596 / 205386 / 5772308 min/median/max
- primary_size_distribution_bytes: 19596 / 42563.6 / 105248 / 205386 / 277120 / 425795.6 / 5772308 min/p10/p25/median/p75/p90/max
- primary_same_size_fraction: 0.008197

| series_id | role | kind | width | samples | values | bytes | value distribution min/p10/p25/median/p75/p90/max | byte distribution min/p10/p25/median/p75/p90/max | same-size fraction | missing files |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| `google_fonts_ofl_font_binaries` | primary | uint | 8 | 122 | 33876096 | 33876096 | 19596 / 42563.6 / 105248 / 205386 / 277120 / 425795.6 / 5772308 | 19596 / 42563.6 / 105248 / 205386 / 277120 / 425795.6 / 5772308 | 0.008197 | 0 |

## `natural_earth_vector_shp_u8`

- status: `ok`
- reasons: `none`
- primary_samples: 12
- primary_values: 96390016
- primary_bytes: 96390016
- primary_value_count_range: 25104 / 6986842 / 23766908 min/median/max
- primary_size_range_bytes: 25104 / 6986842 / 23766908 min/median/max
- primary_size_distribution_bytes: 25104 / 47898.8 / 2063354 / 6986842 / 10233802 / 20350555.6 / 23766908 min/p10/p25/median/p75/p90/max
- primary_same_size_fraction: 0.083333

| series_id | role | kind | width | samples | values | bytes | value distribution min/p10/p25/median/p75/p90/max | byte distribution min/p10/p25/median/p75/p90/max | same-size fraction | missing files |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| `natural_earth_10m_shp_geometry` | primary | uint | 8 | 12 | 96390016 | 96390016 | 25104 / 47898.8 / 2063354 / 6986842 / 10233802 / 20350555.6 / 23766908 | 25104 / 47898.8 / 2063354 / 6986842 / 10233802 / 20350555.6 / 23766908 | 0.083333 | 0 |
