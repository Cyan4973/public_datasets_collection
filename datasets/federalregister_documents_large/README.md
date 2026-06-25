# Federal Register Document Page Metrics (per month)

Numeric Federal Register document page metrics, organized as **one family per quantity**
with **one sample per publication month** — "many month-series of the same quantity".
Supersedes the earlier recipe, which captured only the first 1,000 documents of 2024 and
extracted text-field *byte lengths* (title/abstract length) rather than numeric quantities.

- Source: https://www.federalregister.gov/api/v1/documents.json (Federal Register API v1)
- Local raw payloads: `${DATA_DIR:-.data}/downloads/federalregister_documents_large/pages/`

## Families & samples

| family | quantity | type |
|---|---|---|
| `fedreg_page_length_u16` | printed pages a document occupies | uint16 |
| `fedreg_start_page_u32` | start page within the annual FR volume | uint32 |

- **A sample** = one publication month's values of a single quantity.
- **Samples/family** = number of months with `>= FEDREG_MIN_RECORDS` non-constant values
  (default 1000).
- `page_length` is a genuine small-count quantity with a long tail (most documents are a
  few pages, big rules run to hundreds — so it needs u16). `start_page` runs 1 → ~100,000
  within a year (so it needs u32) and is monotonic within each year.

## Why shard by month

The API caps `count` at 10,000 per query, so a whole-year query truncates. A month
(~2,000–3,500 documents) stays well under the cap and is fully retrieved with a short
`per_page=1000` page-loop. Documents are de-duplicated by `document_number`.

## Run

```sh
bash datasets/federalregister_documents_large/download.sh   # months x ~3 small pages each
bash datasets/federalregister_documents_large/build.sh
bash datasets/federalregister_documents_large/verify.sh
```

Tuning env vars: `FEDREG_START_YEAR` (default 2010), `FEDREG_END_YEAR` (default 2024),
`FEDREG_SLEEP` (default 0.2s), `FEDREG_MIN_RECORDS` (default 1000), `FEDREG_UA`. The crawl
is resumable: already-downloaded `pages/<YYYY-MM>_pNN.json` files are skipped. Logs under
`${DATA_DIR:-.data}/logs/federalregister_documents_large/`.
