# OpenAlex Author Topic Count U8

Focused OpenAlex author-topic-count extraction for compression training.

This recipe downloads only the author `id` and embedded `topics` list from the
OpenAlex authors API, converts `len(topics)` to uint8, and emits deterministic
contiguous shards.

Selected scope:
- source endpoint: `https://api.openalex.org/authors`
- fields: `id,topics`
- default cap: `5,000,000` author rows
- default minimum download: `2,000,000` author rows
- default shard size: `262,144` uint8 values
- one homogeneous family: embedded author topic-list length

Verified output from the first repaired collection:
- `11` homogeneous shards
- `2,858,800` uint8 values
- `2,858,800` primary sample bytes
- histogram: `0=5945`, `1=100`, `2=124`, `3=5434`, `4=1062`,
  `5=2846135`

The value is intentionally the embedded list length, not a full author topic
cardinality. OpenAlex commonly returns five topic objects for authors with at
least five displayed topics, so the resulting stream has a strong capped-value
structure that is useful as targeted compression training material.

Series emitted by `build.sh`:
- `openalex_author_topic_count_u8` (`uint8`, little-endian)

Usage:

```sh
bash datasets/openalex_author_topic_count_u8/download.sh
bash datasets/openalex_author_topic_count_u8/build.sh
bash datasets/openalex_author_topic_count_u8/verify.sh
```

Tuning environment variables:
- `OPENALEX_TOPIC_COUNT_MAX_RECORDS`
- `OPENALEX_TOPIC_COUNT_MIN_RECORDS`
- `OPENALEX_TOPIC_COUNT_PAGE_SIZE` (`<=200`)
- `OPENALEX_TOPIC_COUNT_REQUEST_DELAY_SECONDS`
- `OPENALEX_TOPIC_COUNT_SHARD_VALUES`
- `OPENALEX_TOPIC_COUNT_MIN_FINAL_SHARD_VALUES`
- `OPENALEX_TOPIC_COUNT_STOP_ON_429_AFTER_MIN`
- `OPENALEX_TOPIC_COUNT_MAX_429_SLEEP_SECONDS`
- `OPENALEX_MAILTO`

If OpenAlex returns HTTP `429` after the minimum row count has already been
cached, `download.sh` stops cleanly and writes stats for the cached prefix
instead of waiting on a very long `Retry-After`.

Local layout under `${DATA_DIR:-.data}`:
- `downloads/openalex_author_topic_count_u8/pages/topic_count_page_<page>.json`
- `downloads/openalex_author_topic_count_u8/download_stats.json`
- `filtered/openalex_author_topic_count_u8/ingest_stats.json`
- `index/openalex_author_topic_count_u8/samples.jsonl`
- `samples/openalex_author_topic_count_u8/openalex_author_topic_count_u8/part<shard>_n<values>.bin`
- `logs/openalex_author_topic_count_u8/*.latest.log`

No padding, synthesis, interpolation, or quantization beyond the native uint8
list-length representation is applied.
