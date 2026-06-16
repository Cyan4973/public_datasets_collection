# Dataset State Report

Acceptance floor used by this report: at least `10000` primary values, at least `102400` primary bytes, median primary sample size at least `1000` values, and primary output at most `1000000000` bytes.

## `europe_pmc_search`

- status: `ok`
- reasons: `none`
- primary_samples: 6
- primary_values: 1127748
- primary_bytes: 2631412
- primary_value_count_range: 187958 / 187958 / 187958 min/median/max
- primary_size_range_bytes: 375916 / 375916 / 751832 min/median/max
- primary_size_distribution_bytes: 375916 / 375916 / 375916 / 375916 / 375916 / 563874 / 751832 min/p10/p25/median/p75/p90/max
- primary_same_size_fraction: 0.833333

| series_id | role | kind | width | samples | values | bytes | value distribution min/p10/p25/median/p75/p90/max | byte distribution min/p10/p25/median/p75/p90/max | same-size fraction | missing files |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| `europepmc_author_count` | primary | uint | 16 | 1 | 187958 | 375916 | 187958 / 187958 / 187958 / 187958 / 187958 / 187958 / 187958 | 375916 / 375916 / 375916 / 375916 / 375916 / 375916 / 375916 | 1.000000 | 0 |
| `europepmc_cited_by_count` | primary | uint | 32 | 1 | 187958 | 751832 | 187958 / 187958 / 187958 / 187958 / 187958 / 187958 / 187958 | 751832 / 751832 / 751832 / 751832 / 751832 / 751832 / 751832 | 1.000000 | 0 |
| `europepmc_first_publication_date` | auxiliary | uint | 32 | 1 | 187958 | 751832 | 187958 / 187958 / 187958 / 187958 / 187958 / 187958 / 187958 | 751832 / 751832 / 751832 / 751832 / 751832 / 751832 / 751832 | 1.000000 | 0 |
| `europepmc_fulltext_id_count` | primary | uint | 16 | 1 | 187958 | 375916 | 187958 / 187958 / 187958 / 187958 / 187958 / 187958 / 187958 | 375916 / 375916 / 375916 / 375916 / 375916 / 375916 / 375916 | 1.000000 | 0 |
| `europepmc_journal_title_length` | primary | uint | 16 | 1 | 187958 | 375916 | 187958 / 187958 / 187958 / 187958 / 187958 / 187958 / 187958 | 375916 / 375916 / 375916 / 375916 / 375916 / 375916 / 375916 | 1.000000 | 0 |
| `europepmc_pub_type_count` | primary | uint | 16 | 1 | 187958 | 375916 | 187958 / 187958 / 187958 / 187958 / 187958 / 187958 / 187958 | 375916 / 375916 / 375916 / 375916 / 375916 / 375916 / 375916 | 1.000000 | 0 |
| `europepmc_title_length` | primary | uint | 16 | 1 | 187958 | 375916 | 187958 / 187958 / 187958 / 187958 / 187958 / 187958 / 187958 | 375916 / 375916 / 375916 / 375916 / 375916 / 375916 / 375916 | 1.000000 | 0 |

