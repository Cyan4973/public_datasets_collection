# Citi Bike January 2024 Station IDs

Exact-id backfill for `citibike_2024_01_station_ids_u16`.

This recipe preserves the January 2024 Citi Bike trip ZIP member order and CSV
row order. It emits two aligned `uint16` series:
- `citibike_start_station_id`
- `citibike_end_station_id`

Both series use the same global first-seen dictionary:
- code `0` is reserved for missing station ids
- non-empty station ids receive shared global `uint16` codes in first-seen order

Usage:

```sh
bash datasets/citibike_2024_01_station_ids_u16/download.sh
bash datasets/citibike_2024_01_station_ids_u16/build.sh
bash datasets/citibike_2024_01_station_ids_u16/verify.sh
```

Optional local archive override:

```sh
CITIBIKE_ARCHIVE=/absolute/path/to/202401-citibike-tripdata.zip \
  bash datasets/citibike_2024_01_station_ids_u16/download.sh
```

Outputs:
- source ZIP:
  - `${DATA_DIR:-.data}/downloads/citibike_2024_01_station_ids_u16/202401-citibike-tripdata.zip`
- filtered stats:
  - `${DATA_DIR:-.data}/filtered/citibike_2024_01_station_ids_u16/ingest_stats.json`
- samples:
  - `${DATA_DIR:-.data}/samples/citibike_2024_01_station_ids_u16/citibike_start_station_id/partNNN.bin`
  - `${DATA_DIR:-.data}/samples/citibike_2024_01_station_ids_u16/citibike_end_station_id/partNNN.bin`
- sample index:
  - `${DATA_DIR:-.data}/index/citibike_2024_01_station_ids_u16/samples.jsonl`

Notes:
- `download.sh` validates the ZIP size and SHA-256.
- `build.sh` preserves ZIP member order and CSV row order within each member.
- `build.sh` uses the same fixed 8 aligned shard lengths as the sibling public-datasets recipe.
