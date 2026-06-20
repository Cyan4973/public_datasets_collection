# MetaCPAN Releases Search Large

Paginated MetaCPAN **release** table, extracted into one numeric column sample per release-level field.

- Source: https://fastapi.metacpan.org/v1/release/_search (MetaCPAN public Elasticsearch API)
- Scope: the **full** MetaCPAN release index (~hundreds of thousands of releases), walked in ascending `date` order via Elasticsearch `search_after` (which bypasses the 10,000 `from`/`size` window). `_source` filtering keeps pages small. `METACPAN_MAX_RECORDS` caps the pull (default 500k — effectively the whole index); `METACPAN_MIN_RECORDS` is the floor. Rows are de-duplicated by `_id`. (The full index spans 1995→present, so dependency/test fields vary across old and modern releases.)
- Local raw pages: `${DATA_DIR:-.data}/downloads/metacpan_releases_search_large/pages/`

## Series (each a `table_column` sample, one value per release row)

| series_id | field | type |
|---|---|---|
| `metacpan_version_numified` | `version_numified` | float64 |
| `metacpan_stat_size` | `stat.size` | uint32 |
| `metacpan_stat_mtime` | `stat.mtime` | uint32 |
| `metacpan_dependency_count` | `len(dependency)` | uint16 |
| `metacpan_provides_count` | `len(provides)` | uint16 |
| `metacpan_tests_pass` | `tests.pass` | uint32 |
| `metacpan_tests_fail` | `tests.fail` | uint32 |
| `metacpan_tests_na` | `tests.na` | uint32 |
| `metacpan_tests_unknown` | `tests.unknown` | uint32 |

Rows missing the required `version_numified` scalar are dropped atomically so all columns stay equal length.

## Run

```sh
bash datasets/metacpan_releases_search_large/download.sh
bash datasets/metacpan_releases_search_large/build.sh
bash datasets/metacpan_releases_search_large/verify.sh
```

Tuning env vars: `METACPAN_MAX_RECORDS`, `METACPAN_MIN_RECORDS`, `METACPAN_PAGE_SIZE`, `METACPAN_REQUEST_DELAY_SECONDS`. Logs under `${DATA_DIR:-.data}/logs/metacpan_releases_search_large/`.
