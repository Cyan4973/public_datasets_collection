# Macrostrat More Sources State

Expansion probe attempted additional Macrostrat API endpoints. Accepted
resources were promoted to dataset recipes; rejected and failed probes are
documented here to avoid repeating the same dead ends.

## Successful Resources

| candidate | source bytes | records | outcome |
|---|---:|---:|---|
| `macrostrat_columns_long` | 5,228,161 | 3,462 | promoted to `macrostrat_columns` |
| `macrostrat_sections_long` | 15,049,802 | 11,315 | promoted to `macrostrat_sections` |

## Accepted Outputs

| dataset | primary samples | primary values | primary bytes | median sample values |
|---|---:|---:|---:|---:|
| `macrostrat_columns` | 9 | 31,155 | 124,620 | 3,462 |
| `macrostrat_sections` | 6 | 67,885 | 271,540 | 11,315 |

## Failed Or Rejected Probes

| candidate | status | detail | interpretation |
|---|---|---|---|
| `macrostrat_measurements_long` | failed | HTTP 500 from `https://macrostrat.org/api/measurements?response=long` | Not definitive; likely needs narrower measurement parameters rather than full-table `response=long`. |
| `macrostrat_def_intervals` | rejected | semantic validation found API documentation payload, not data rows | Tiny endpoint-definition metadata, not training material. |
| `macrostrat_def_columns` | rejected | semantic validation found API documentation payload, not data rows | Tiny endpoint-definition metadata, not training material. |
| `macrostrat_def_lithologies` | rejected | semantic validation found API documentation payload, not data rows | Tiny endpoint-definition metadata, not training material. |
| `macrostrat_def_environments` | rejected | semantic validation found API documentation payload, not data rows | Tiny endpoint-definition metadata, not training material. |
| `macrostrat_def_econs` | rejected | semantic validation found API documentation payload, not data rows | Tiny endpoint-definition metadata, not training material. |

Next Macrostrat opportunity is the measurements table, but it should be probed
with explicit measurement class/type parameters instead of the all-measurements
URL that returned HTTP 500.
