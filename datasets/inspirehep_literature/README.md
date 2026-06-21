# INSPIRE-HEP Literature Bibliometrics (per year)

Bibliometric counts from the public INSPIRE-HEP literature corpus, organized as
**one family per quantity** with **one sample per publication year** — "many
year-series of the same physical quantity" (like NIH per-year / USGS sites).
Supersedes the earlier single `q=electron&size=1000` recipe (which mixed counts with
record timestamps and held one sample per field).

- Source: https://inspirehep.net/api/literature (open INSPIRE metadata)
- Local raw payloads: `${DATA_DIR:-.data}/downloads/inspirehep_literature/pages/`

## Families & samples

| family | quantity | type |
|---|---|---|
| `inspirehep_citation_count_u32` | citations per paper | uint32 |
| `inspirehep_author_count_u16` | authors per paper | uint16 |
| `inspirehep_page_count_u16` | pages per paper | uint16 (if populated) |
| `inspirehep_reference_count_u16` | references per paper | uint16 (if populated) |

- **A sample** = one publication year's values of a single quantity (e.g. all 2015
  papers' citation counts). Years are derived from `earliest_date`.
- **Samples/family** = number of qualifying years (those with
  `>= INSPIRE_MIN_YEAR_RECORDS` non-constant values; default 1000). citation and author
  counts are always present; page/reference families are emitted only if the API
  populates those fields for enough years.
- Each family is one quantity across years; citations, authors, pages and references
  are never mixed.

## Why sharded by year

INSPIRE caps deep paging at `size * page <= 10000`, so the crawl is sharded per year
(`date YYYY`) and capped at `INSPIRE_MAX_PAGES` pages/year. The year query is only a
fetch shard: the build re-derives each record's canonical year and de-duplicates by
`control_number`, so a paper matched under two date years is counted once. Only scalar
fields are projected — no author lists or reference arrays are downloaded.

## Run

```sh
bash datasets/inspirehep_literature/download.sh   # ~250-350 small paged JSON requests
bash datasets/inspirehep_literature/build.sh
bash datasets/inspirehep_literature/verify.sh
```

Tuning env vars: `INSPIRE_START_YEAR`/`INSPIRE_END_YEAR` (default 1960/2024),
`INSPIRE_MAX_PAGES` (default 5 → up to 5000 records/year), `INSPIRE_SIZE` (default 1000),
`INSPIRE_MIN_YEAR_RECORDS` (default 1000), `INSPIRE_YEAR_QUERY` (default `date %s`).
Logs under `${DATA_DIR:-.data}/logs/inspirehep_literature/`.
