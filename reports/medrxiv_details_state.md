# Dataset State Report

Acceptance floor used by this report: at least `10000` primary values, at least `102400` primary bytes, median primary sample size at least `1000` values, and primary output at most `1000000000` bytes.

## `medrxiv_details`

- status: `ok`
- reasons: `none`
- primary_samples: 5
- primary_values: 77615
- primary_bytes: 186276
- primary_value_count_range: 15523 / 15523 / 15523 min/median/max
- primary_size_range_bytes: 31046 / 31046 / 62092 min/median/max
- primary_size_distribution_bytes: 31046 / 31046 / 31046 / 31046 / 31046 / 49673.6 / 62092 min/p10/p25/median/p75/p90/max
- primary_same_size_fraction: 0.800000

| series_id | role | kind | width | samples | values | bytes | value distribution min/p10/p25/median/p75/p90/max | byte distribution min/p10/p25/median/p75/p90/max | same-size fraction | missing files |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| `medrxiv_details_abstract_length` | primary | uint | 32 | 1 | 15523 | 62092 | 15523 / 15523 / 15523 / 15523 / 15523 / 15523 / 15523 | 62092 / 62092 / 62092 / 62092 / 62092 / 62092 / 62092 | 1.000000 | 0 |
| `medrxiv_details_author_count` | primary | uint | 16 | 1 | 15523 | 31046 | 15523 / 15523 / 15523 / 15523 / 15523 / 15523 / 15523 | 31046 / 31046 / 31046 / 31046 / 31046 / 31046 / 31046 | 1.000000 | 0 |
| `medrxiv_details_corresponding_institution_length` | primary | uint | 16 | 1 | 15523 | 31046 | 15523 / 15523 / 15523 / 15523 / 15523 / 15523 / 15523 | 31046 / 31046 / 31046 / 31046 / 31046 / 31046 / 31046 | 1.000000 | 0 |
| `medrxiv_details_date` | auxiliary | uint | 32 | 1 | 15523 | 62092 | 15523 / 15523 / 15523 / 15523 / 15523 / 15523 / 15523 | 62092 / 62092 / 62092 / 62092 / 62092 / 62092 / 62092 | 1.000000 | 0 |
| `medrxiv_details_title_length` | primary | uint | 16 | 1 | 15523 | 31046 | 15523 / 15523 / 15523 / 15523 / 15523 / 15523 / 15523 | 31046 / 31046 / 31046 / 31046 / 31046 / 31046 / 31046 | 1.000000 | 0 |
| `medrxiv_details_version` | primary | uint | 16 | 1 | 15523 | 31046 | 15523 / 15523 / 15523 / 15523 / 15523 / 15523 / 15523 | 31046 / 31046 / 31046 / 31046 / 31046 / 31046 / 31046 | 1.000000 | 0 |
