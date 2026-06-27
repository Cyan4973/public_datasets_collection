#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="weathergov_stations"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
DOWNLOAD_DIR="$REPO_ROOT/$DATA_DIR/downloads/$DATASET_ID"
FILTER_DIR="$REPO_ROOT/$DATA_DIR/filtered/$DATASET_ID"
INDEX_DIR="$REPO_ROOT/$DATA_DIR/index/$DATASET_ID"
SAMPLES_DIR="$REPO_ROOT/$DATA_DIR/samples/$DATASET_ID"
mkdir -p "$LOG_DIR" "$DOWNLOAD_DIR" "$FILTER_DIR" "$INDEX_DIR" "$SAMPLES_DIR"

RUN_TS="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="$LOG_DIR/build.$RUN_TS.log"
LATEST_LOG="$LOG_DIR/build.latest.log"
exec > >(tee "$LOG_FILE" "$LATEST_LOG") 2>&1

echo "[$(date -Is)] build start dataset=$DATASET_ID"

export REPO_ROOT DATA_DIR DOWNLOAD_DIR FILTER_DIR INDEX_DIR SAMPLES_DIR
export WEATHERGOV_MIN_STATIONS="${WEATHERGOV_MIN_STATIONS:-1000}"
python3 - <<'PY'
from __future__ import annotations

import json
import math
import os
import shutil
import statistics
import struct
from pathlib import Path

DATASET_ID = "weathergov_stations"
repo_root = Path(os.environ["REPO_ROOT"])
data_root = repo_root / os.environ["DATA_DIR"]
download_dir = Path(os.environ["DOWNLOAD_DIR"])
filter_dir = Path(os.environ["FILTER_DIR"])
index_dir = Path(os.environ["INDEX_DIR"])
samples_dir = Path(os.environ["SAMPLES_DIR"])
min_stations = int(os.environ["WEATHERGOV_MIN_STATIONS"])

page_dir = download_dir / "pages"
page_files = sorted(page_dir.glob("page_*.json"))
if not page_files:
    legacy = download_dir / "weathergov_stations.json"
    if legacy.is_file():
        page_files = [legacy]
if not page_files:
    raise SystemExit(f"missing local weather.gov pages under {page_dir}; run download.sh first")

for child in samples_dir.glob("*"):
    if child.is_dir():
        shutil.rmtree(child)
index_dir.mkdir(parents=True, exist_ok=True)
filter_dir.mkdir(parents=True, exist_ok=True)

series_meta = {
    "weathergov_station_lon_f64": ("float", 64, 8, "d"),
    "weathergov_station_lat_f64": ("float", 64, 8, "d"),
    "weathergov_station_elevation_m_f32": ("float", 32, 4, "f"),
}
values: dict[str, list[float]] = {series_id: [] for series_id in series_meta}
seen: set[str] = set()
skipped = 0
duplicates = 0
source_features = 0

for page_file in page_files:
    obj = json.loads(page_file.read_text(encoding="utf-8"))
    features = obj.get("features")
    if not isinstance(features, list):
        raise SystemExit(f"{page_file}: missing features list")
    source_features += len(features)
    for feature in features:
        props = feature.get("properties") or {}
        station_id = str(props.get("stationIdentifier") or feature.get("id") or props.get("@id") or "")
        if station_id and station_id in seen:
            duplicates += 1
            continue
        try:
            coords = feature["geometry"]["coordinates"]
            lon = float(coords[0])
            lat = float(coords[1])
            elevation_obj = props.get("elevation") or {}
            elevation = float(elevation_obj.get("value"))
        except Exception:
            skipped += 1
            continue
        if not (math.isfinite(lon) and math.isfinite(lat) and math.isfinite(elevation)):
            skipped += 1
            continue
        if not (-180.0 <= lon <= 180.0 and -90.0 <= lat <= 90.0):
            skipped += 1
            continue
        if not (-500.0 <= elevation <= 10000.0):
            skipped += 1
            continue
        if station_id:
            seen.add(station_id)
        values["weathergov_station_lon_f64"].append(lon)
        values["weathergov_station_lat_f64"].append(lat)
        values["weathergov_station_elevation_m_f32"].append(elevation)

station_count = len(values["weathergov_station_lon_f64"])
if station_count < min_stations:
    raise SystemExit(f"only {station_count} retained stations < WEATHERGOV_MIN_STATIONS={min_stations}; rerun download.sh")

rows = []
for series_id, (kind, bits, element_size, code) in series_meta.items():
    series_values = values[series_id]
    if len(series_values) != station_count:
        raise SystemExit(f"series length mismatch for {series_id}")
    if min(series_values) == max(series_values):
        raise SystemExit(f"constant series: {series_id}")
    out_dir = samples_dir / series_id
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"{series_id}_n{len(series_values):06d}.bin"
    with out.open("wb") as fh:
        for offset in range(0, len(series_values), 8192):
            chunk = series_values[offset : offset + 8192]
            fh.write(struct.pack("<" + code * len(chunk), *chunk))
    rows.append(
        {
            "dataset_id": DATASET_ID,
            "series_id": series_id,
            "role": "primary",
            "sample_path": out.relative_to(data_root).as_posix(),
            "numeric_kind": kind,
            "bit_width": bits,
            "endianness": "little",
            "element_size_bytes": element_size,
            "sample_size_bytes": out.stat().st_size,
            "value_count": len(series_values),
            "sample_format": f"raw homogeneous {kind}{bits} array",
            "sample_geometry": "station_catalog_column",
            "sample_rank": 1,
            "sample_shape": [len(series_values)],
            "sample_axes": ["station"],
            "min": min(series_values),
            "max": max(series_values),
        }
    )

counts = [int(row["value_count"]) for row in rows]
byte_counts = [int(row["sample_size_bytes"]) for row in rows]
if sum(counts) < 10_000 and sum(byte_counts) < 102_400:
    raise SystemExit(f"below aggregate floor: values={sum(counts)} bytes={sum(byte_counts)}")
if statistics.median(counts) < 1_000:
    raise SystemExit(f"median sample values below floor: {statistics.median(counts)}")

(filter_dir / "ingest_stats.json").write_text(
    json.dumps(
        {
            "dataset_id": DATASET_ID,
            "source_pages": len(page_files),
            "source_features": source_features,
            "retained_stations": station_count,
            "skipped_features": skipped,
            "duplicate_features": duplicates,
            "primary_values": sum(counts),
            "primary_sample_bytes": sum(byte_counts),
            "median_primary_values": statistics.median(counts),
        },
        indent=2,
        sort_keys=True,
    )
    + "\n",
    encoding="utf-8",
)
with (index_dir / "samples.jsonl").open("w", encoding="utf-8") as fh:
    for row in rows:
        fh.write(json.dumps(row, sort_keys=True) + "\n")
print(
    f"built samples={len(rows)} retained_stations={station_count} "
    f"values={sum(counts)} bytes={sum(byte_counts)} skipped={skipped} duplicates={duplicates}"
)
PY

echo "[$(date -Is)] build done dataset=$DATASET_ID"
