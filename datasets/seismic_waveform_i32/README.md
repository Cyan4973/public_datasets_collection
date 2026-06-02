# IRIS Seismic Waveform Counts

Exact-id backfill for `seismic_waveform_i32`.

This recipe uses the same fixed 12 waveform windows as the sibling
public-datasets repo. It preserves the IRIS ASCII `COUNTS` integer values
exactly and emits one little-endian `int32` sample per source window.

Usage:

```sh
bash datasets/seismic_waveform_i32/download.sh
bash datasets/seismic_waveform_i32/build.sh
bash datasets/seismic_waveform_i32/verify.sh
```

Outputs:
- raw ASCII windows:
  - `${DATA_DIR:-.data}/downloads/seismic_waveform_i32/*.ascii`
- download plan:
  - `${DATA_DIR:-.data}/downloads/seismic_waveform_i32/download_plan.tsv`
- filtered stats:
  - `${DATA_DIR:-.data}/filtered/seismic_waveform_i32/ingest_stats.json`
- samples:
  - `${DATA_DIR:-.data}/samples/seismic_waveform_i32/seismic_waveform_i32/*.bin`
- sample index:
  - `${DATA_DIR:-.data}/index/seismic_waveform_i32/samples.jsonl`

Notes:
- `download.sh` validates parsed sample counts for every fetched ASCII file.
- `build.sh` preserves the final `COUNTS` column exactly as signed int32.
- `verify.sh` checks raw file presence, output sizes, and sample index rows.
