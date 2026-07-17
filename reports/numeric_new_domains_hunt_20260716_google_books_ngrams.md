# Numeric New Domains Hunt: Google Books Ngram Counts

## Recommendation

Stage `google_books_1gram_counts_2020_eng_u64`, using one fixed Google Books Ngram 2020 English 1-gram gzip shard.

## Why This Adds New Territory

- Domain: diachronic language-use frequency counts from digitized books.
- Shape: many token-year observations with integer year, match-count, and volume-count fields.
- Difference from accepted datasets: the catalog has Gutenberg token ID streams, but not aggregate historical language-frequency count series.
- Numeric representation: source decimal observation triples are emitted as one uint16 year stream and two uint64 count streams; token text is excluded from primary samples.

## Materiality

The selected public shard is about 265 MB compressed. The build truncates at an observation boundary before the 1 GB primary-output cap, while requiring at least 20 million observations. At full default cap this should produce up to about 950 MB of primary binary data.

The recipe enforces:

- source download hard cap: 1,000,000,000 bytes
- default source download cap: 800,000,000 bytes
- download observation floor: 10,000,000 validated observations
- build observation floor: 20,000,000 observations
- verify value floor: 60,000,000 values
- verify primary-byte floor: 400,000,000 bytes
- primary-output hard cap: 1,000,000,000 bytes

## Script To Run

```bash
bash staging/google_books_1gram_counts_2020_eng_u64/download.sh
```

After the download succeeds, build and verify locally:

```bash
bash staging/google_books_1gram_counts_2020_eng_u64/build.sh
bash staging/google_books_1gram_counts_2020_eng_u64/verify.sh
```

## Failed Candidate Triage

- KDD Cup 1999 was retired because UCI's modern package contains path-pointer placeholders and the original full-data host returned 403.
- UNSW-NB15 was retired because the official split CSV file endpoint returned 401 before any data could be retrieved.

## Acceptance Outcome

The Google Books Ngram shard downloaded, built, and verified successfully.

- source gzip bytes: 265,116,429
- validated download observations: at least 10,000,146
- build observations: 52,777,777
- primary samples: 3
- primary values: 158,333,331
- primary bytes: 949,999,986
- source lines processed: 1,211,656
- observed year range: 1470 to 2019
- output cap behavior: truncated at an observation boundary before the 1 GB cap
