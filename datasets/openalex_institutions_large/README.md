# OpenAlex Institutions Large

Cursor-paginated OpenAlex **institutions** table, extracted into one numeric column sample per institution-level field.

- Source: https://api.openalex.org/institutions (CC0)
- Scope: the **full** OpenAlex institutions index (~126k institutions) in default cursor order. `OPENALEX_MAX_RECORDS` caps the pull (default effectively unlimited); `OPENALEX_MIN_RECORDS` is the floor the download must reach.
- Local raw pages: `${DATA_DIR:-.data}/downloads/openalex_institutions_large/pages/`

## Series (each a `table_column` sample, one value per institution row)

| series_id | field | type |
|---|---|---|
| `openalex_inst_works_count` | `works_count` | uint32 |
| `openalex_inst_cited_by_count` | `cited_by_count` | uint32 |
| `openalex_inst_h_index` | `summary_stats.h_index` | uint32 |
| `openalex_inst_i10_index` | `summary_stats.i10_index` | uint32 |
| `openalex_inst_repo_count` | `len(repositories)` | uint16 |
| `openalex_inst_role_count` | `len(roles)` | uint8 |
| `openalex_inst_assoc_count` | `len(associated_institutions)` | uint16 |

Rows missing a required scalar (`works_count`, `cited_by_count`) are dropped atomically so all columns stay equal length.

## Run

```sh
bash datasets/openalex_institutions_large/download.sh
bash datasets/openalex_institutions_large/build.sh
bash datasets/openalex_institutions_large/verify.sh
```

Tuning env vars: `OPENALEX_MAX_RECORDS`, `OPENALEX_MIN_RECORDS`, `OPENALEX_PAGE_SIZE` (≤200), `OPENALEX_REQUEST_DELAY_SECONDS`, `OPENALEX_MAILTO` (polite pool). Logs under `${DATA_DIR:-.data}/logs/openalex_institutions_large/`.
