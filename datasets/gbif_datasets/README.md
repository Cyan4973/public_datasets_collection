# GBIF Datasets

Paged GBIF dataset catalog metadata. The recipe emits homogeneous numeric
table-column samples for dataset record counts, keyword-list cardinalities, and
decade-list cardinalities.

Source URL template:
- `https://api.gbif.org/v1/dataset/search?limit={limit}&offset={offset}`

Selected series:
- `gbif_record_count_u64`
- `gbif_keyword_count_u16`
- `gbif_decade_count_u16`

Download knobs:
- `GBIF_PAGE_SIZE` defaults to `1000`.
- `GBIF_MAX_PAGES` defaults to `100`.
- `GBIF_MAX_RECORDS` defaults to `100000`.
- `GBIF_MIN_RECORDS` defaults to `5000`.
- `GBIF_REQUEST_DELAY_SECONDS` defaults to `0.1`.

Build knobs:
- `GBIF_MIN_RETAINED_RECORDS` defaults to `5000`.
