# Crossref Works Large

Large cursor-paginated Crossref **2024 works** table, extracted into one numeric column **family** per native field.

- Source: https://api.crossref.org/works (Crossref REST, CC0)
- Scope: the first `CROSSREF_MAX_RECORDS` (default **1,500,000**) works published in 2024, via cursor pagination with `select=` field projection. De-duplicated by DOI.
- Local raw pages: `${DATA_DIR:-.data}/downloads/crossref_works_large_retry/pages/`

## Families (one numeric column per field)

| family (series_id) | field | type |
|---|---|---|
| `crossref_reference_count_u32` | `reference-count` | uint32 |
| `crossref_is_referenced_by_count_u32` | `is-referenced-by-count` | uint32 |
| `crossref_created_ts_u64` | `created.timestamp` (ms) | uint64 |
| `crossref_deposited_ts_u64` | `deposited.timestamp` (ms) | uint64 |
| `crossref_indexed_ts_u64` | `indexed.timestamp` (ms) | uint64 |
| `crossref_link_count_u16` | `len(link)` | uint16 |
| `crossref_license_count_u16` | `len(license)` | uint16 |
| `crossref_member_id_u32` | `member` | uint32 |

## Family / sample structure

Each family is a **single column** of ~1.5M values (one per work). Crossref has no
natural per-entity files, so rather than a few small natural samples, each family is
made **large enough (>1M values) for the training selector to shard into independent
samples**. `verify.sh` enforces the ≥1,000,000-values-per-family floor.

- **8 families**, 1 column each, **~1.5M values/family** (selector-shardable)
- per-family bytes: u16 ≈ 3 MB, u32 ≈ 6 MB, u64 ≈ 12 MB; **total ≈ 55 MB**

Rows missing any required scalar (`reference-count`, `is-referenced-by-count`, the three timestamps, `member`) are dropped atomically so all columns stay equal length. (`published_year` is omitted: under the 2024 filter it would be constant.)

## Run

```sh
bash datasets/crossref_works_large_retry/download.sh
bash datasets/crossref_works_large_retry/build.sh
bash datasets/crossref_works_large_retry/verify.sh
```

Tuning env vars: `CROSSREF_MAX_RECORDS`, `CROSSREF_MIN_RECORDS`, `CROSSREF_ROWS`, `CROSSREF_FILTER`, `CROSSREF_REQUEST_DELAY_SECONDS`, `CROSSREF_MAILTO` (polite pool). Logs under `${DATA_DIR:-.data}/logs/crossref_works_large_retry/`.
