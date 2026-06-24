# Hugging Face Model Downloads & Likes (per year)

Numeric Hugging Face model metrics, organized as **one family per quantity** with **one
sample per model creation year** — "many year-series of the same quantity". Supersedes the
earlier single ~500-model page recipe (which also mixed in derived counts).

- Source: https://huggingface.co/api/models (Hub API)
- Local raw payloads: `${DATA_DIR:-.data}/downloads/huggingface_models_large/pages/`

## Families & samples

| family | quantity | type |
|---|---|---|
| `hf_downloads_u32` | 30-day download count | uint32 |
| `hf_likes_u32` | like count | uint32 |

- **A sample** = one creation year's values of a single quantity. Years come from `createdAt`.
- **Samples/family** = number of years with `>= HF_MIN_YEAR_RECORDS` non-constant values
  (default 1000).

## Why sort by downloads

The models are fetched **sorted by downloads desc** via cursor pagination (the API returns
a `Link: rel="next"` header). This keeps the fetched head dense (download counts are all
non-zero), avoiding a zero-dominated distribution. De-duplicated by model id.

## Run

```sh
bash datasets/huggingface_models_large/download.sh   # ~250 cursor pages
bash datasets/huggingface_models_large/build.sh
bash datasets/huggingface_models_large/verify.sh
```

Tuning env vars: `HF_START_URL`, `HF_MAX_PAGES` (default 250), `HF_SLEEP` (default 0.4),
`HF_MIN_YEAR_RECORDS` (default 1000). Logs under
`${DATA_DIR:-.data}/logs/huggingface_models_large/`.
