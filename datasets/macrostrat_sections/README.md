# Macrostrat Sections

Macrostrat stratigraphic section summary table from the public Macrostrat API.
Sections are a distinct natural table grain from units and columns, so this
recipe emits one homogeneous sample per selected section-table numeric field.

Source:

- `https://macrostrat.org/api/sections?response=long`

Validated local run:

- source records: 11,315
- source bytes: 15,049,802
- primary samples: 6
- primary values: 67,885
- primary sample bytes: 271,540
- primary value count range: 11,312 / 11,315 / 11,315 min/median/max

Selected primary series:

- `macrostrat_section_t_age_f32`
- `macrostrat_section_b_age_f32`
- `macrostrat_section_area_f32`
- `macrostrat_section_max_thick_f32`
- `macrostrat_section_min_thick_f32`
- `macrostrat_section_pbdb_collections_u32`

Missing-value policy: missing or unparsable values are dropped per field. Series
are not concatenated; each output sample is exactly one Macrostrat section-table
field.
