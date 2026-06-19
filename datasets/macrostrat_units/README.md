# Macrostrat Units

Macrostrat stratigraphic unit numeric fields from the public units API. This
recipe emits one homogeneous sample per unit-table geology or paleontology
field.

Source:

- `https://macrostrat.org/api/units?response=long`

Cleanup note: the legacy recipe emitted unit IDs, section IDs, column IDs, and
unit centroid coordinates as primary series. Those fields are no longer emitted.

Validated local run:

- source records: 129,304
- source bytes: 404,092,601
- primary samples: 11
- primary values: 1,422,089
- primary sample bytes: 5,688,356
- primary value count range: 129,261 / 129,262 / 129,304 min/median/max
- removed legacy outputs: `macrostrat_unit_id`, `macrostrat_section_id`,
  `macrostrat_col_id`, `macrostrat_clat`, `macrostrat_clng`

Selected primary series:

- `macrostrat_unit_t_age_f32`
- `macrostrat_unit_b_age_f32`
- `macrostrat_unit_t_interval_age_f32`
- `macrostrat_unit_b_interval_age_f32`
- `macrostrat_unit_t_interval_position_f32`
- `macrostrat_unit_b_interval_position_f32`
- `macrostrat_unit_max_thick_f32`
- `macrostrat_unit_min_thick_f32`
- `macrostrat_unit_column_area_f32`
- `macrostrat_unit_pbdb_collections_u32`
- `macrostrat_unit_pbdb_occurrences_u32`

Missing-value policy: missing or unparsable values are dropped per field. Series
are not concatenated; each output sample is exactly one Macrostrat unit-table
field.
