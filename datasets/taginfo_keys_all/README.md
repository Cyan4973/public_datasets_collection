# Taginfo Keys All

Paged OpenStreetMap Taginfo key statistics. The recipe emits homogeneous
numeric table-column samples: element counts, distinct-value counts, user
counts, wiki presence, and the `uint16` Taginfo project-count field.

Source URL template:
- `https://taginfo.openstreetmap.org/api/4/keys/all?page={page}&rp={page_size}`

Download knobs:
- `TAGINFO_PAGE_SIZE` defaults to `500`.
- `TAGINFO_MAX_PAGES` defaults to `200`.
- `TAGINFO_MAX_RECORDS` defaults to `100000`.
- `TAGINFO_MIN_RECORDS` defaults to `2000`.
- `TAGINFO_REQUEST_DELAY_SECONDS` defaults to `0.2`.
