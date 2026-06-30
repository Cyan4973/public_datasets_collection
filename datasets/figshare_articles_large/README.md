# Figshare Articles Large

Bounded Figshare article listing. The default download target is 20,000 article
records, not a single API page.

Selected series:
- `figshare_id_u32`
- `figshare_defined_type_u16`
- `figshare_group_id_u32`
- `figshare_published_timestamp_i64`
- `figshare_created_timestamp_i64`
- `figshare_modified_timestamp_i64`

Missing-value policy: filters rows with invalid timestamps or missing required numeric fields.

Download knobs:
- `FIGSHARE_ARTICLES_LARGE_TARGET_RECORDS` defaults to `20000`.
- `FIGSHARE_ARTICLES_LARGE_MIN_RECORDS` defaults to `17000`.
- `FIGSHARE_ARTICLES_LARGE_PAGE_SIZE` defaults to `1000`.
- `FIGSHARE_ARTICLES_LARGE_MAX_PAGES_PER_SLICE` defaults to `10`.
- `FIGSHARE_ARTICLES_LARGE_ORDER_FIELD` defaults to `published_date`.
- `FIGSHARE_ARTICLES_LARGE_ORDER_DIRECTIONS` defaults to `desc asc`.
- `FIGSHARE_ARTICLES_LARGE_REQUEST_DELAY_SECONDS` defaults to `1`.
