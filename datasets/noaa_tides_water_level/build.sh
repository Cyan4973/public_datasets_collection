#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR=$(cd "$(dirname "$0")/../.." && pwd)
DATA_DIR=${DATA_DIR:-"$ROOT_DIR/.data"}
DATASET_ID=noaa_tides_water_level
DOWNLOAD_DIR="$DATA_DIR/downloads/$DATASET_ID"
FILTERED_DIR="$DATA_DIR/filtered/$DATASET_ID"
SAMPLES_DIR="$DATA_DIR/samples/$DATASET_ID"
INDEX_DIR="$DATA_DIR/index/$DATASET_ID"
LOG_DIR="$DATA_DIR/logs/$DATASET_ID"
mkdir -p "$FILTERED_DIR" "$SAMPLES_DIR" "$INDEX_DIR" "$LOG_DIR"

RUN_TS=$(date -u +%Y%m%dT%H%M%SZ)
LOG_FILE="$LOG_DIR/build.$RUN_TS.log"
LATEST_LOG="$LOG_DIR/build.latest.log"
exec > >(tee "$LOG_FILE" "$LATEST_LOG") 2>&1

MIN_VALUES_PER_SAMPLE="${NOAA_TIDES_MIN_VALUES_PER_SAMPLE:-100000}"

DOWNLOAD_DIR="$DOWNLOAD_DIR" \
FILTERED_DIR="$FILTERED_DIR" \
SAMPLES_DIR="$SAMPLES_DIR" \
INDEX_DIR="$INDEX_DIR" \
DATA_DIR="$DATA_DIR" \
MIN_VALUES_PER_SAMPLE="$MIN_VALUES_PER_SAMPLE" \
python3 - <<'PY'
from __future__ import annotations

import array
import csv
import json
import math
import os
import shutil
from datetime import datetime
from pathlib import Path

download_dir = Path(os.environ["DOWNLOAD_DIR"])
filtered_dir = Path(os.environ["FILTERED_DIR"])
samples_dir = Path(os.environ["SAMPLES_DIR"])
index_dir = Path(os.environ["INDEX_DIR"])
data_root = Path(os.environ["DATA_DIR"])
min_values_per_sample = int(os.environ["MIN_VALUES_PER_SAMPLE"])
dataset_id = "noaa_tides_water_level"

plan_path = download_dir / "download_plan.tsv"
if not plan_path.is_file():
    raise SystemExit(f"missing download plan: {plan_path}")

if samples_dir.exists():
    shutil.rmtree(samples_dir)
samples_dir.mkdir(parents=True, exist_ok=True)
index_dir.mkdir(parents=True, exist_ok=True)
filtered_dir.mkdir(parents=True, exist_ok=True)

series_defs = {
    "noaa_tides_level_f64": ("float", 64, "d"),
    "noaa_tides_sigma_f64": ("float", 64, "d"),
}
for series_id in series_defs:
    (samples_dir / series_id).mkdir(parents=True, exist_ok=True)

station_meta: dict[str, str] = {}
station_values: dict[str, dict[str, list[float]]] = {}
stats_rows = []
rows_total = 0
rows_skipped = 0

with plan_path.open("r", encoding="utf-8", newline="") as fh:
    reader = csv.DictReader(fh, delimiter="\t")
    for row in reader:
        station_id = row["station_id"]
        station_name = row["station_name"]
        station_meta[station_id] = station_name
        station_values.setdefault(station_id, {series_id: [] for series_id in series_defs})
        path = download_dir / row["rel_out"]
        if not path.is_file():
            raise SystemExit(f"missing downloaded chunk: {path}")
        payload = json.loads(path.read_text(encoding="utf-8"))
        data = payload.get("data", [])
        chunk_total = len(data)
        chunk_kept = 0
        chunk_skipped = 0
        seen_timestamps: set[str] = set()
        for item in data:
            rows_total += 1
            try:
                timestamp = str(item["t"])
                if timestamp in seen_timestamps:
                    raise ValueError("duplicate timestamp within chunk")
                seen_timestamps.add(timestamp)
                datetime.strptime(timestamp, "%Y-%m-%d %H:%M")
                level = float(item["v"])
                sigma = float(item["s"])
                if not math.isfinite(level) or not math.isfinite(sigma):
                    raise ValueError("non-finite value")
            except Exception:
                rows_skipped += 1
                chunk_skipped += 1
                continue
            station_values[station_id]["noaa_tides_level_f64"].append(level)
            station_values[station_id]["noaa_tides_sigma_f64"].append(sigma)
            chunk_kept += 1
        stats_rows.append(
            {
                "station_id": station_id,
                "station_name": station_name,
                "begin_date": row["begin_date"],
                "end_date": row["end_date"],
                "rows_total": chunk_total,
                "rows_kept": chunk_kept,
                "rows_skipped": chunk_skipped,
            }
        )

index_rows = []
series_sample_counts = {series_id: 0 for series_id in series_defs}
series_value_counts = {series_id: 0 for series_id in series_defs}
rejected_samples = []

for station_id in sorted(station_values):
    station_name = station_meta[station_id]
    station_slug = f"station_{station_id}"
    for series_id, (numeric_kind, bit_width, array_code) in series_defs.items():
        values = station_values[station_id][series_id]
        if len(values) < min_values_per_sample:
            rejected_samples.append(
                {
                    "station_id": station_id,
                    "station_name": station_name,
                    "series_id": series_id,
                    "value_count": len(values),
                    "reason": "below_min_values_per_sample",
                }
            )
            continue
        arr = array.array(array_code, values)
        if arr.itemsize > 1 and os.sys.byteorder != "little":
            arr.byteswap()
        out_path = samples_dir / series_id / f"{station_slug}.bin"
        out_path.write_bytes(arr.tobytes())
        sample_size = out_path.stat().st_size
        index_rows.append(
            {
                "dataset_id": dataset_id,
                "series_id": series_id,
                "role": "primary",
                "sample_path": out_path.relative_to(data_root).as_posix(),
                "numeric_kind": numeric_kind,
                "bit_width": bit_width,
                "endianness": "little",
                "element_size_bytes": bit_width // 8,
                "sample_size_bytes": sample_size,
                "value_count": len(values),
                "sample_geometry": "noaa_coops_station_time_series",
                "sample_rank": 1,
                "sample_shape": [len(values)],
                "station_id": station_id,
                "station_name": station_name,
                "natural_record_kind": "noaa_coops_water_level_observation",
                "natural_record_count": len(values),
                "natural_record_values": 1,
            }
        )
        series_sample_counts[series_id] += 1
        series_value_counts[series_id] += len(values)

with (index_dir / "samples.jsonl").open("w", encoding="utf-8") as fh:
    for row in index_rows:
        fh.write(json.dumps(row, sort_keys=True) + "\n")

with (filtered_dir / "chunk_stats.tsv").open("w", encoding="utf-8", newline="") as fh:
    writer = csv.DictWriter(
        fh,
        fieldnames=["station_id", "station_name", "begin_date", "end_date", "rows_total", "rows_kept", "rows_skipped"],
        delimiter="\t",
    )
    writer.writeheader()
    writer.writerows(stats_rows)

stats = {
    "dataset_id": dataset_id,
    "min_values_per_sample": min_values_per_sample,
    "primary_sample_bytes": sum(int(row["sample_size_bytes"]) for row in index_rows),
    "primary_values": sum(int(row["value_count"]) for row in index_rows),
    "rejected_samples": rejected_samples,
    "rows_skipped": rows_skipped,
    "rows_total": rows_total,
    "sample_count": len(index_rows),
    "series_sample_counts": series_sample_counts,
    "series_value_counts": series_value_counts,
    "stations_planned": len(station_meta),
}
(filtered_dir / "ingest_stats.json").write_text(json.dumps(stats, indent=2, sort_keys=True) + "\n", encoding="utf-8")
print(
    f"built samples={len(index_rows)} primary_values={stats['primary_values']} "
    f"primary_bytes={stats['primary_sample_bytes']} rows_skipped={rows_skipped}"
)
PY

echo "[$(date -Is)] build done dataset=$DATASET_ID"
