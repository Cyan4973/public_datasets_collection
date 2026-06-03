# OpenF1 Belgium 2023 Native Car Data

Public OpenF1 `car_data` telemetry for the 2023 Belgian Grand Prix Qualifying
session (`session_key=9135`), preserved as native per-driver numeric fields.

This recipe avoids the rejected quantized exact-id path and instead keeps the
direct OpenF1 numeric fields:
- `speed`
- `rpm`
- `throttle`
- `brake`
- `n_gear`
- `drs`

Usage:

```sh
bash datasets/openf1_belgium_2023_car_data_native/download.sh
bash datasets/openf1_belgium_2023_car_data_native/build.sh
bash datasets/openf1_belgium_2023_car_data_native/verify.sh
```

Optional local source override:

```sh
OPENF1_BELGIUM_2023_CAR_DATA_NATIVE_SOURCE_DIR=/absolute/path/to/json_dir \
  bash datasets/openf1_belgium_2023_car_data_native/download.sh
```

Expected local outputs:
- raw JSON:
  - `${DATA_DIR:-.data}/downloads/openf1_belgium_2023_car_data_native/car_data_s9135_d*.json`
- filtered stats:
  - `${DATA_DIR:-.data}/filtered/openf1_belgium_2023_car_data_native/ingest_stats.json`
- samples:
  - `${DATA_DIR:-.data}/samples/openf1_belgium_2023_car_data_native/<series_id>/openf1_<series_id>_d<driver>_n<sample_count>.bin`
- sample index:
  - `${DATA_DIR:-.data}/index/openf1_belgium_2023_car_data_native/samples.jsonl`

Notes:
- `download.sh` validates that the pinned session key is still returned by the
  OpenF1 sessions endpoint and that the driver roster is non-empty.
- `build.sh` performs no network access and preserves the native numeric field
  values directly after a stable sort by `date`.
- `verify.sh` checks raw file presence, per-series sample counts, byte sizes,
  and the generated index.
