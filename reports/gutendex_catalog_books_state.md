# Dataset State Report

Acceptance floor used by this report: at least `10000` primary values, at least `102400` primary bytes, median primary sample size at least `1000` values, and primary output at most `1000000000` bytes.

## `gutendex_catalog_books`

- status: `ok`
- reasons: `none`
- primary_samples: 3
- primary_values: 203883
- primary_bytes: 565180
- primary_value_count_range: 62588 / 62588 / 78707 min/median/max
- primary_size_range_bytes: 125176 / 125176 / 314828 min/median/max
- primary_size_distribution_bytes: 125176 / 125176 / 125176 / 125176 / 220002 / 276897.6 / 314828 min/p10/p25/median/p75/p90/max
- primary_same_size_fraction: 0.666667

| series_id | role | kind | width | samples | values | bytes | value distribution min/p10/p25/median/p75/p90/max | byte distribution min/p10/p25/median/p75/p90/max | same-size fraction | missing files |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| `gutendex_author_birth_year_i16` | primary | int | 16 | 1 | 62588 | 125176 | 62588 / 62588 / 62588 / 62588 / 62588 / 62588 / 62588 | 125176 / 125176 / 125176 / 125176 / 125176 / 125176 / 125176 | 1.000000 | 0 |
| `gutendex_author_death_year_i16` | primary | int | 16 | 1 | 62588 | 125176 | 62588 / 62588 / 62588 / 62588 / 62588 / 62588 / 62588 | 125176 / 125176 / 125176 / 125176 / 125176 / 125176 / 125176 | 1.000000 | 0 |
| `gutendex_book_id_u32` | auxiliary | uint | 32 | 1 | 78707 | 314828 | 78707 / 78707 / 78707 / 78707 / 78707 / 78707 / 78707 | 314828 / 314828 / 314828 / 314828 / 314828 / 314828 / 314828 | 1.000000 | 0 |
| `gutendex_download_count_u32` | primary | uint | 32 | 1 | 78707 | 314828 | 78707 / 78707 / 78707 / 78707 / 78707 / 78707 / 78707 | 314828 / 314828 / 314828 / 314828 / 314828 / 314828 / 314828 | 1.000000 | 0 |

