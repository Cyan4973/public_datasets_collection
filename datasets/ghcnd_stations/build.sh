#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR=$(cd "$(dirname "$0")/../.." && pwd)
DATA_DIR=${DATA_DIR:-"$ROOT_DIR/.data"}
DATASET_ID=ghcnd_stations
DOWNLOAD_DIR="$DATA_DIR/downloads/$DATASET_ID"
FILTERED_DIR="$DATA_DIR/filtered/$DATASET_ID"
SAMPLES_DIR="$DATA_DIR/samples/$DATASET_ID"
INDEX_DIR="$DATA_DIR/index/$DATASET_ID"
LOG_DIR="$DATA_DIR/logs/$DATASET_ID"
mkdir -p "$FILTERED_DIR" "$SAMPLES_DIR" "$INDEX_DIR" "$LOG_DIR"

TS=$(date +%Y%m%d_%H%M%S)
LOG_FILE="$LOG_DIR/build.$TS.log"
LATEST_LOG="$LOG_DIR/build.latest.log"
exec > >(tee "$LOG_FILE") 2>&1

python3 - <<'PY' "$DOWNLOAD_DIR/ghcnd-stations.txt" "$FILTERED_DIR" "$SAMPLES_DIR" "$INDEX_DIR"
import json, os, struct, sys
src, filtered_dir, samples_dir, index_dir = sys.argv[1:5]

series = {
    "ghcnd_station_latitude_f32": [],
    "ghcnd_station_longitude_f32": [],
    "ghcnd_station_elevation_f32": [],
}
rows_total = 0
rows_kept = 0
with open(src, "r", encoding="utf-8") as f:
    for line in f:
        rows_total += 1
        try:
            lat = float(line[12:20].strip())
            lon = float(line[21:30].strip())
            elev = float(line[31:37].strip())
        except Exception:
            continue
        series["ghcnd_station_latitude_f32"].append(lat)
        series["ghcnd_station_longitude_f32"].append(lon)
        series["ghcnd_station_elevation_f32"].append(elev)
        rows_kept += 1

with open(os.path.join(index_dir, "samples.jsonl"), "w", encoding="utf-8") as idx:
    for sid, vals in series.items():
        sdir = os.path.join(samples_dir, sid)
        os.makedirs(sdir, exist_ok=True)
        out = os.path.join(sdir, "stations.bin")
        with open(out, "wb") as f:
            for v in vals:
                f.write(struct.pack("<f", v))
        idx.write(json.dumps({
            "dataset_id": "ghcnd_stations",
            "series_id": sid,
            "sample_path": out,
            "numeric_kind": "float",
            "bit_width": 32,
            "endianness": "little",
            "element_size_bytes": 4,
            "sample_size_bytes": os.path.getsize(out),
            "value_count": len(vals),
        }) + "\n")

with open(os.path.join(filtered_dir, "ingest_stats.json"), "w", encoding="utf-8") as f:
    json.dump({"rows_total": rows_total, "rows_kept": rows_kept, "rows_skipped": rows_total - rows_kept, "sample_rows": len(series)}, f)

print("build done dataset=ghcnd_stations")
PY

cp "$LOG_FILE" "$LATEST_LOG" 2>/dev/null || true
