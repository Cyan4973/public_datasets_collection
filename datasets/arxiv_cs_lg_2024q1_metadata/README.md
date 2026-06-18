# arXiv cs.LG 2024 Q1 Metadata

Accepted replacement for the below-floor `arxiv_cs_recent` recipe.

This recipe collects a fixed arXiv API submitted-date window for `cs.LG`
papers from `2024-01-01T00:00` through `2024-03-31T23:59`. It emits
homogeneous numeric metadata columns from the Atom entries: published timestamp,
updated timestamp, author count, and category count.

Natural sample boundary: one bounded arXiv result table column for the fixed
category/date window. The recipe does not concatenate unrelated categories or
ranked feeds; it replaces the old moving "recent" first page with a reproducible
time window.

Run:

```bash
bash datasets/arxiv_cs_lg_2024q1_metadata/download.sh
bash datasets/arxiv_cs_lg_2024q1_metadata/build.sh
bash datasets/arxiv_cs_lg_2024q1_metadata/verify.sh
```

The download script honors arXiv API politeness with a default 3-second delay
between requests. Use `DRY_RUN=1` to inspect the page plan without fetching.
