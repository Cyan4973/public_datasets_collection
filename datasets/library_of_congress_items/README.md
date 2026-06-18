# Library of Congress Items

Bounded Library of Congress item-search metadata recipe.

This repairs the original one-page recipe by downloading a fixed prefix of LOC
item result pages. The default is `150` pages at `100` records per page, giving
about `15,000` catalog results before field-level missing-value filtering.

Primary series:

- `loc_extract_timestamp_u32`: LOC extraction timestamp as Unix seconds.
- `loc_numeric_shelf_id_u64`: numeric shelf identifier where present.
- `loc_resource_files_sum_u32`: sum of resource `files` counts per item.
- `loc_resource_segments_sum_u32`: sum of resource `segments` counts per item.
- `loc_item_date_year_u16`: first parseable item year from LOC date fields.

Natural sample boundary: one numeric field across the bounded LOC item result
set. Missing fields are dropped independently per series; the samples are not
aligned feature vectors.

Download stage for the user:

```bash
bash datasets/library_of_congress_items/download.sh
```

Processing stage after downloads complete:

```bash
bash datasets/library_of_congress_items/build.sh
bash datasets/library_of_congress_items/verify.sh
```

Useful bounds:

```bash
LOC_PAGE_COUNT=150 LOC_PER_PAGE=100 bash datasets/library_of_congress_items/download.sh
```

Validated repair state:

```text
page_files: 150
source_records: 15,000
source_bytes: 75,957,159
primary_samples: 5
primary_values: 66,380
primary_bytes: 264,316
median_primary_values: 15,000
primary_value_range: 6,926 .. 15,000
```

Per-series material:

```text
loc_extract_timestamp_u32       values=15,000 bytes=60,000
loc_item_date_year_u16          values=14,454 bytes=28,908
loc_numeric_shelf_id_u64        values=6,926  bytes=55,408
loc_resource_files_sum_u32      values=15,000 bytes=60,000
loc_resource_segments_sum_u32   values=15,000 bytes=60,000
```
