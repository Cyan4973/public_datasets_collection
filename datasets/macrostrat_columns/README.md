# Macrostrat Columns

Macrostrat stratigraphic column summary table from the public Macrostrat API.
This recipe is separate from `macrostrat_units`: columns are a different natural
table grain and are emitted as one homogeneous sample per numeric column field.

Source:

- `https://macrostrat.org/api/columns?response=long`

Validated local run:

- source records: 3,462
- source bytes: 5,228,161
- primary samples: 9
- primary values: 31,155
- primary sample bytes: 124,620
- primary value count range: 3,460 / 3,462 / 3,462 min/median/max

Selected primary series:

- `macrostrat_column_t_age_f32`
- `macrostrat_column_b_age_f32`
- `macrostrat_column_area_f32`
- `macrostrat_column_max_thick_f32`
- `macrostrat_column_max_min_thick_f32`
- `macrostrat_column_min_min_thick_f32`
- `macrostrat_column_pbdb_collections_u32`
- `macrostrat_column_section_count_u32`
- `macrostrat_column_unit_count_u32`

Missing-value policy: missing or unparsable values are dropped per field. Series
are not concatenated; each output sample is exactly one Macrostrat column-table
field.
