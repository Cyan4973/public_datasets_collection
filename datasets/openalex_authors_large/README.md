# OpenAlex Authors Large

Cursor-paginated OpenAlex **authors** table, extracted into one numeric column sample per author-level field.

- Source: https://api.openalex.org/authors (CC0)
- Scope: the first `OPENALEX_TARGET_RECORDS` (default `20000`) authors in OpenAlex default cursor order — a bounded, reproducible slice, not a ranked top-N leaderboard.
- Local raw pages: `${DATA_DIR:-.data}/downloads/openalex_authors_large/pages/`

## Series (each a `table_column` sample, one value per author row)

| series_id | field | type |
|---|---|---|
| `openalex_author_works_count_u32` | `works_count` | uint32 |
| `openalex_author_cited_by_count_u32` | `cited_by_count` | uint32 |
| `openalex_author_h_index_u16` | `summary_stats.h_index` | uint16 |
| `openalex_author_i10_index_u32` | `summary_stats.i10_index` | uint32 |
| `openalex_author_raw_name_count_u8` | `len(raw_author_names)` | uint8 |
| `openalex_author_affiliation_count_u16` | `len(affiliations)` | uint16 |
| `openalex_author_topic_count_u8` | `len(topics)` | uint8 |

Rows missing a required scalar (`works_count`, `cited_by_count`) are dropped atomically so all columns stay equal length.

## Run

```sh
bash datasets/openalex_authors_large/download.sh
bash datasets/openalex_authors_large/build.sh
bash datasets/openalex_authors_large/verify.sh
```

Tuning env vars: `OPENALEX_TARGET_RECORDS`, `OPENALEX_PAGE_SIZE` (≤200), `OPENALEX_REQUEST_DELAY_SECONDS`, `OPENALEX_MAILTO` (polite pool). Logs under `${DATA_DIR:-.data}/logs/openalex_authors_large/`.
