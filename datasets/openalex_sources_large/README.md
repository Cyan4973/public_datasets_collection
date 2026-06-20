# OpenAlex Sources Large

Cursor-paginated OpenAlex **sources** table, extracted into one numeric column sample per source-level field.

- Source: https://api.openalex.org/sources (CC0)
- Scope: the first `OPENALEX_TARGET_RECORDS` (default `20000`) sources in OpenAlex default cursor order — a bounded, reproducible slice, not a ranked top-N leaderboard.
- Local raw pages: `${DATA_DIR:-.data}/downloads/openalex_sources_large/pages/`

## Series (each a `table_column` sample, one value per source row)

| series_id | field | type |
|---|---|---|
| `openalex_source_works_count_u32` | `works_count` | uint32 |
| `openalex_source_oa_works_count_u32` | `oa_works_count` | uint32 |
| `openalex_source_cited_by_count_u32` | `cited_by_count` | uint32 |
| `openalex_source_2yr_mean_citedness_f32` | `summary_stats.2yr_mean_citedness` | float32 |
| `openalex_source_h_index_u16` | `summary_stats.h_index` | uint16 |
| `openalex_source_i10_index_u32` | `summary_stats.i10_index` | uint32 |
| `openalex_source_first_publication_year_u16` | `first_publication_year` | uint16 |
| `openalex_source_last_publication_year_u16` | `last_publication_year` | uint16 |
| `openalex_source_topic_count_u8` | `len(topics)` | uint8 |

Rows missing any required scalar (`works_count`, `oa_works_count`, `cited_by_count`, `first_publication_year`, `last_publication_year`) are dropped atomically so all columns stay equal length.

## Run

```sh
bash datasets/openalex_sources_large/download.sh
bash datasets/openalex_sources_large/build.sh
bash datasets/openalex_sources_large/verify.sh
```

Tuning env vars: `OPENALEX_TARGET_RECORDS`, `OPENALEX_PAGE_SIZE` (≤200), `OPENALEX_REQUEST_DELAY_SECONDS`, `OPENALEX_MAILTO` (polite pool). Logs under `${DATA_DIR:-.data}/logs/openalex_sources_large/`.
