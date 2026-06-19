# Dataset State Report

Acceptance floor used by this report: at least `10000` primary values, at least `102400` primary bytes, median primary sample size at least `1000` values, and primary output at most `1000000000` bytes.

## `macrostrat_columns`

- status: `ok`
- reasons: `none`
- primary_samples: 9
- primary_values: 31155
- primary_bytes: 124620
- primary_value_count_range: 3460 / 3462 / 3462 min/median/max
- primary_size_range_bytes: 13840 / 13848 / 13848 min/median/max
- primary_size_distribution_bytes: 13840 / 13843.2 / 13848 / 13848 / 13848 / 13848 / 13848 min/p10/p25/median/p75/p90/max
- primary_same_size_fraction: 0.777778

| series_id | role | kind | width | samples | values | bytes | value distribution min/p10/p25/median/p75/p90/max | byte distribution min/p10/p25/median/p75/p90/max | same-size fraction | missing files |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| `macrostrat_column_area_f32` | primary | float | 32 | 1 | 3462 | 13848 | 3462 / 3462 / 3462 / 3462 / 3462 / 3462 / 3462 | 13848 / 13848 / 13848 / 13848 / 13848 / 13848 / 13848 | 1.000000 | 0 |
| `macrostrat_column_b_age_f32` | primary | float | 32 | 1 | 3461 | 13844 | 3461 / 3461 / 3461 / 3461 / 3461 / 3461 / 3461 | 13844 / 13844 / 13844 / 13844 / 13844 / 13844 / 13844 | 1.000000 | 0 |
| `macrostrat_column_max_min_thick_f32` | primary | float | 32 | 1 | 3462 | 13848 | 3462 / 3462 / 3462 / 3462 / 3462 / 3462 / 3462 | 13848 / 13848 / 13848 / 13848 / 13848 / 13848 / 13848 | 1.000000 | 0 |
| `macrostrat_column_max_thick_f32` | primary | float | 32 | 1 | 3462 | 13848 | 3462 / 3462 / 3462 / 3462 / 3462 / 3462 / 3462 | 13848 / 13848 / 13848 / 13848 / 13848 / 13848 / 13848 | 1.000000 | 0 |
| `macrostrat_column_min_min_thick_f32` | primary | float | 32 | 1 | 3462 | 13848 | 3462 / 3462 / 3462 / 3462 / 3462 / 3462 / 3462 | 13848 / 13848 / 13848 / 13848 / 13848 / 13848 / 13848 | 1.000000 | 0 |
| `macrostrat_column_pbdb_collections_u32` | primary | uint | 32 | 1 | 3462 | 13848 | 3462 / 3462 / 3462 / 3462 / 3462 / 3462 / 3462 | 13848 / 13848 / 13848 / 13848 / 13848 / 13848 / 13848 | 1.000000 | 0 |
| `macrostrat_column_section_count_u32` | primary | uint | 32 | 1 | 3462 | 13848 | 3462 / 3462 / 3462 / 3462 / 3462 / 3462 / 3462 | 13848 / 13848 / 13848 / 13848 / 13848 / 13848 / 13848 | 1.000000 | 0 |
| `macrostrat_column_t_age_f32` | primary | float | 32 | 1 | 3460 | 13840 | 3460 / 3460 / 3460 / 3460 / 3460 / 3460 / 3460 | 13840 / 13840 / 13840 / 13840 / 13840 / 13840 / 13840 | 1.000000 | 0 |
| `macrostrat_column_unit_count_u32` | primary | uint | 32 | 1 | 3462 | 13848 | 3462 / 3462 / 3462 / 3462 / 3462 / 3462 / 3462 | 13848 / 13848 / 13848 / 13848 / 13848 / 13848 / 13848 | 1.000000 | 0 |

## `macrostrat_sections`

- status: `ok`
- reasons: `none`
- primary_samples: 6
- primary_values: 67885
- primary_bytes: 271540
- primary_value_count_range: 11312 / 11315 / 11315 min/median/max
- primary_size_range_bytes: 45248 / 45260 / 45260 min/median/max
- primary_size_distribution_bytes: 45248 / 45250 / 45254 / 45260 / 45260 / 45260 / 45260 min/p10/p25/median/p75/p90/max
- primary_same_size_fraction: 0.666667

| series_id | role | kind | width | samples | values | bytes | value distribution min/p10/p25/median/p75/p90/max | byte distribution min/p10/p25/median/p75/p90/max | same-size fraction | missing files |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| `macrostrat_section_area_f32` | primary | float | 32 | 1 | 11315 | 45260 | 11315 / 11315 / 11315 / 11315 / 11315 / 11315 / 11315 | 45260 / 45260 / 45260 / 45260 / 45260 / 45260 / 45260 | 1.000000 | 0 |
| `macrostrat_section_b_age_f32` | primary | float | 32 | 1 | 11313 | 45252 | 11313 / 11313 / 11313 / 11313 / 11313 / 11313 / 11313 | 45252 / 45252 / 45252 / 45252 / 45252 / 45252 / 45252 | 1.000000 | 0 |
| `macrostrat_section_max_thick_f32` | primary | float | 32 | 1 | 11315 | 45260 | 11315 / 11315 / 11315 / 11315 / 11315 / 11315 / 11315 | 45260 / 45260 / 45260 / 45260 / 45260 / 45260 / 45260 | 1.000000 | 0 |
| `macrostrat_section_min_thick_f32` | primary | float | 32 | 1 | 11315 | 45260 | 11315 / 11315 / 11315 / 11315 / 11315 / 11315 / 11315 | 45260 / 45260 / 45260 / 45260 / 45260 / 45260 / 45260 | 1.000000 | 0 |
| `macrostrat_section_pbdb_collections_u32` | primary | uint | 32 | 1 | 11315 | 45260 | 11315 / 11315 / 11315 / 11315 / 11315 / 11315 / 11315 | 45260 / 45260 / 45260 / 45260 / 45260 / 45260 / 45260 | 1.000000 | 0 |
| `macrostrat_section_t_age_f32` | primary | float | 32 | 1 | 11312 | 45248 | 11312 / 11312 / 11312 / 11312 / 11312 / 11312 / 11312 | 45248 / 45248 / 45248 / 45248 / 45248 / 45248 / 45248 | 1.000000 | 0 |
