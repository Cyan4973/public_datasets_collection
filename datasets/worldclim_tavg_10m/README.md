# WorldClim 10m Average Temperature

Exact-id backfill for `worldclim_tavg_10m`.

This recipe uses the same fixed six-band subset as the sibling public-datasets
repo. It preserves source GeoTIFF float32 values exactly, including the native
NoData sentinel.

Usage:

```sh
bash datasets/worldclim_tavg_10m/download.sh
bash datasets/worldclim_tavg_10m/build.sh
bash datasets/worldclim_tavg_10m/verify.sh
```

Optional local-archive override:

```sh
WORLDCLIM_ARCHIVE=/absolute/path/to/wc2.1_10m_tavg.zip \
  bash datasets/worldclim_tavg_10m/download.sh
```

Outputs:
- source archive:
  - `${DATA_DIR:-.data}/downloads/worldclim_tavg_10m/wc2.1_10m_tavg.zip`
- filtered stats:
  - `${DATA_DIR:-.data}/filtered/worldclim_tavg_10m/ingest_stats.json`
- samples:
  - `${DATA_DIR:-.data}/samples/worldclim_tavg_10m/worldclim_tavg_f32/*.bin`
- sample index:
  - `${DATA_DIR:-.data}/index/worldclim_tavg_10m/samples.jsonl`

Notes:
- `download.sh` validates archive byte size and SHA-256 before accepting the file.
- `build.sh` does no network access and decodes only the selected monthly row
  bands from local files.
- `verify.sh` checks archive integrity, sample sizes, index row count, and
  value counts.
