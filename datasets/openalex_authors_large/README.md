# OpenAlex Authors Large

Cursor-paginated OpenAlex **authors** table, extracted into one numeric column sample per author-level field.

- Source: https://api.openalex.org/authors (CC0)
- Scope: a large bounded slice of the OpenAlex authors index (default cap **1,000,000** authors; the full index is ~118M) in default cursor order. `OPENALEX_MAX_RECORDS` sets the cap; `OPENALEX_MIN_RECORDS` is the floor the download must reach.
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

Tuning env vars: `OPENALEX_MAX_RECORDS`, `OPENALEX_MIN_RECORDS`, `OPENALEX_PAGE_SIZE` (≤200), `OPENALEX_REQUEST_DELAY_SECONDS`, `OPENALEX_MAILTO` (polite pool). Logs under `${DATA_DIR:-.data}/logs/openalex_authors_large/`.
