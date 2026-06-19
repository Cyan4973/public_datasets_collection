# Dataset State Report

Acceptance floor used by this report: at least `10000` primary values, at least `102400` primary bytes, median primary sample size at least `1000` values, and primary output at most `1000000000` bytes.

## `macrostrat_units`

- status: `ok`
- reasons: `none`
- primary_samples: 11
- primary_values: 1422089
- primary_bytes: 5688356
- primary_value_count_range: 129261 / 129262 / 129304 min/median/max
- primary_size_range_bytes: 517044 / 517048 / 517216 min/median/max
- primary_size_distribution_bytes: 517044 / 517044 / 517046 / 517048 / 517216 / 517216 / 517216 min/p10/p25/median/p75/p90/max
- primary_same_size_fraction: 0.454545

| series_id | role | kind | width | samples | values | bytes | value distribution min/p10/p25/median/p75/p90/max | byte distribution min/p10/p25/median/p75/p90/max | same-size fraction | missing files |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| `macrostrat_unit_b_age_f32` | primary | float | 32 | 1 | 129262 | 517048 | 129262 / 129262 / 129262 / 129262 / 129262 / 129262 / 129262 | 517048 / 517048 / 517048 / 517048 / 517048 / 517048 / 517048 | 1.000000 | 0 |
| `macrostrat_unit_b_interval_age_f32` | primary | float | 32 | 1 | 129262 | 517048 | 129262 / 129262 / 129262 / 129262 / 129262 / 129262 / 129262 | 517048 / 517048 / 517048 / 517048 / 517048 / 517048 / 517048 | 1.000000 | 0 |
| `macrostrat_unit_b_interval_position_f32` | primary | float | 32 | 1 | 129262 | 517048 | 129262 / 129262 / 129262 / 129262 / 129262 / 129262 / 129262 | 517048 / 517048 / 517048 / 517048 / 517048 / 517048 / 517048 | 1.000000 | 0 |
| `macrostrat_unit_column_area_f32` | primary | float | 32 | 1 | 129304 | 517216 | 129304 / 129304 / 129304 / 129304 / 129304 / 129304 / 129304 | 517216 / 517216 / 517216 / 517216 / 517216 / 517216 / 517216 | 1.000000 | 0 |
| `macrostrat_unit_max_thick_f32` | primary | float | 32 | 1 | 129304 | 517216 | 129304 / 129304 / 129304 / 129304 / 129304 / 129304 / 129304 | 517216 / 517216 / 517216 / 517216 / 517216 / 517216 / 517216 | 1.000000 | 0 |
| `macrostrat_unit_min_thick_f32` | primary | float | 32 | 1 | 129304 | 517216 | 129304 / 129304 / 129304 / 129304 / 129304 / 129304 / 129304 | 517216 / 517216 / 517216 / 517216 / 517216 / 517216 / 517216 | 1.000000 | 0 |
| `macrostrat_unit_pbdb_collections_u32` | primary | uint | 32 | 1 | 129304 | 517216 | 129304 / 129304 / 129304 / 129304 / 129304 / 129304 / 129304 | 517216 / 517216 / 517216 / 517216 / 517216 / 517216 / 517216 | 1.000000 | 0 |
| `macrostrat_unit_pbdb_occurrences_u32` | primary | uint | 32 | 1 | 129304 | 517216 | 129304 / 129304 / 129304 / 129304 / 129304 / 129304 / 129304 | 517216 / 517216 / 517216 / 517216 / 517216 / 517216 / 517216 | 1.000000 | 0 |
| `macrostrat_unit_t_age_f32` | primary | float | 32 | 1 | 129261 | 517044 | 129261 / 129261 / 129261 / 129261 / 129261 / 129261 / 129261 | 517044 / 517044 / 517044 / 517044 / 517044 / 517044 / 517044 | 1.000000 | 0 |
| `macrostrat_unit_t_interval_age_f32` | primary | float | 32 | 1 | 129261 | 517044 | 129261 / 129261 / 129261 / 129261 / 129261 / 129261 / 129261 | 517044 / 517044 / 517044 / 517044 / 517044 / 517044 / 517044 | 1.000000 | 0 |
| `macrostrat_unit_t_interval_position_f32` | primary | float | 32 | 1 | 129261 | 517044 | 129261 / 129261 / 129261 / 129261 / 129261 / 129261 / 129261 | 517044 / 517044 / 517044 / 517044 / 517044 / 517044 / 517044 | 1.000000 | 0 |
