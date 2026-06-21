# Wikimedia Daily Pageviews (per article)

Long **daily pageview** series from the public Wikimedia REST API, organized as
**one family per quantity** with **one sample per article** — "many station-series of
the same physical quantity" (like USGS sites / UniProt organisms). Supersedes the
earlier 7-page pinned-2024 recipe.

- Source: https://wikimedia.org/api/rest_v1/ (CC BY-SA 4.0)
- Local raw payloads: `${DATA_DIR:-.data}/downloads/wikimedia_pageviews_daily/{top,series}/`

## Families & samples

| family | quantity | type |
|---|---|---|
| `wikimedia_pageviews_daily_u32` | daily pageviews of one article | uint32 |

- **A sample** = one article's daily pageview series over the full available window
  (default `20150701`–`20241231`, ~3.5k days). Series are naturally variable-length
  (articles created later, or with sparse days, are shorter) — exactly like gauge
  stations with different record lengths.
- **Samples/family** = number of discovered articles (≈150–230 with defaults). Magnitude
  ranges over many orders (a country vs. an obscure topic), but the quantity is identical
  — daily views — so they share one family. Different quantities are never mixed.

## How articles are chosen

1. Fetch the public **top** endpoint for several large projects and a couple of
   reference months (`WIKI_PROJECTS`, `WIKI_REF_MONTHS`).
2. Keep mainspace titles only (drop namespaced `Foo:Bar`, `Main_Page`, and `-`),
   take the top `WIKI_TOP_N` per list, de-duplicate by `(project, article)`.
3. Fetch each article's full daily series; drop series shorter than `WIKI_MIN_DAYS`
   or with constant values.

The reference months default to historical ones to favour evergreen, long-lived pages.

## Run

```sh
bash datasets/wikimedia_pageviews_daily/download.sh   # ~200 small JSON requests
bash datasets/wikimedia_pageviews_daily/build.sh
bash datasets/wikimedia_pageviews_daily/verify.sh
```

Tuning env vars: `WIKI_PROJECTS`, `WIKI_REF_MONTHS` (e.g. `2019/01 2023/01`),
`WIKI_TOP_N` (default 20), `WIKI_START`/`WIKI_END` (default `20150701`/`20241231`),
`WIKI_MIN_DAYS` (default 365). Logs under `${DATA_DIR:-.data}/logs/wikimedia_pageviews_daily/`.
