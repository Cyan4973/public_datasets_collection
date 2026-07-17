# Google Books 2020 English 1-Gram Counts

This staging recipe collects one bounded shard from the Google Books Ngram 2020 English 1-gram corpus and emits numeric yearly count streams.

The domain is diachronic language-use frequency. Source rows contain a 1-gram token and one or more yearly observations; the build excludes token text and writes only numeric observation fields:

- `year_u16`
- `match_count_u64`
- `volume_count_u64`

Run:

```bash
bash staging/google_books_1gram_counts_2020_eng_u64/download.sh
bash staging/google_books_1gram_counts_2020_eng_u64/build.sh
bash staging/google_books_1gram_counts_2020_eng_u64/verify.sh
```

The download script fetches one fixed public gzip shard from Google Cloud Storage and validates the ngram observation format. The build caps primary output below 1 GB by truncating at an observation boundary.
