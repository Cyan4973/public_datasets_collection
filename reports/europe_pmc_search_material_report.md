# Europe PMC Search Material Report

Validated on 2026-06-16 after running the repaired recipe against local
downloads.

## Scope And Source

- Dataset: `europe_pmc_search`
- Query: `FIRST_PDATE:[2024-01-01 TO 2024-01-31]`
- Downloaded pages: `188`
- Raw records: `187,958`
- Unique records: `187,958`
- Duplicate source/id records: `0`
- Source bytes: `147,787,058`
- Local downloaded footprint: about `142 MiB`

## Accepted Output

- Status: `ok`
- Primary samples: `6`
- Auxiliary samples: `1`
- Records kept: `187,958`
- Primary values: `1,127,748`
- Primary bytes: `2,631,412`
- Median primary sample values: `187,958`
- Sample geometry: one homogeneous metadata field sequence sorted by
  firstPublicationDate, source, and record id.

| series_id | role | kind | values | bytes | min | p10 | median | p90 | max | distinct |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| `europepmc_first_publication_date` | auxiliary | uint32 | 187,958 | 751,832 | 1,704,067,200 | 1,704,067,200 | 1,704,758,400 | 1,706,486,400 | 1,706,659,200 | 31 |
| `europepmc_cited_by_count` | primary | uint32 | 187,958 | 751,832 | 0 | 0 | 1 | 10 | 8,001 | 267 |
| `europepmc_author_count` | primary | uint16 | 187,958 | 375,916 | 0 | 2 | 5 | 11 | 5,295 | 128 |
| `europepmc_title_length` | primary | uint16 | 187,958 | 375,916 | 0 | 65 | 109 | 161 | 618 | 360 |
| `europepmc_pub_type_count` | primary | uint16 | 187,958 | 375,916 | 0 | 1 | 2 | 3 | 8 | 9 |
| `europepmc_fulltext_id_count` | primary | uint16 | 187,958 | 375,916 | 0 | 0 | 0 | 1 | 2 | 3 |
| `europepmc_journal_title_length` | primary | uint16 | 187,958 | 375,916 | 0 | 0 | 14 | 24 | 148 | 64 |

## Validation

- `datasets/europe_pmc_search/build.sh` completed locally.
- `datasets/europe_pmc_search/verify.sh` completed locally.
- `reports/accepted_recipe_audit.tsv` now classifies `europe_pmc_search` as
  `ok`.
- `reports/europe_pmc_search_state.md` and
  `reports/europe_pmc_search_state.tsv` contain the generic sample-size state
  report.
