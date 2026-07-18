#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="google_open_buildings_v3_s2_073_geometry_f32"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
DOWNLOAD_DIR="$REPO_ROOT/$DATA_DIR/downloads/$DATASET_ID"
mkdir -p "$LOG_DIR" "$DOWNLOAD_DIR"

RUN_TS="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="$LOG_DIR/download.$RUN_TS.log"
LATEST_LOG="$LOG_DIR/download.latest.log"
exec > >(tee "$LOG_FILE" "$LATEST_LOG") 2>&1

echo "[$(date -Is)] download start dataset=$DATASET_ID"

URL="${OPEN_BUILDINGS_URL:-https://storage.googleapis.com/open-buildings-data/v3/polygons_s2_level_4_gzip/073_buildings.csv.gz}"
TARGET="$DOWNLOAD_DIR/073_buildings.csv.gz"
PLAN="$DOWNLOAD_DIR/download_plan.tsv"
MAX_FILE_BYTES="${OPEN_BUILDINGS_MAX_FILE_BYTES:-800000000}"
HARD_MAX_FILE_BYTES=1000000000
MIN_ROWS="${OPEN_BUILDINGS_MIN_ROWS:-500000}"

if (( MAX_FILE_BYTES > HARD_MAX_FILE_BYTES )); then
  echo "requested max file size $MAX_FILE_BYTES exceeds hard cap $HARD_MAX_FILE_BYTES; clamping"
  MAX_FILE_BYTES="$HARD_MAX_FILE_BYTES"
fi

printf 'resource_id\turl\tfile\nopen_buildings_v3_s2_073\t%s\t%s\n' "$URL" "$(basename "$TARGET")" > "$PLAN"

if [[ -s "$TARGET" && "${FORCE_DOWNLOAD:-0}" != "1" ]]; then
  echo "cache_hit path=$TARGET"
else
  echo "fetch url=$URL"
  curl --globoff -fL --retry 3 --retry-delay 5 --max-filesize "$MAX_FILE_BYTES" \
    -A "openzl-public-datasets/1.0 (numeric dataset collection)" \
    -o "$TARGET.tmp" "$URL"
  mv "$TARGET.tmp" "$TARGET"
fi

export TARGET DOWNLOAD_DIR URL MAX_FILE_BYTES MIN_ROWS
python3 - <<'PY'
from __future__ import annotations

import csv
import gzip
import json
import math
import os
from pathlib import Path

target = Path(os.environ["TARGET"])
download_dir = Path(os.environ["DOWNLOAD_DIR"])
max_file_bytes = int(os.environ["MAX_FILE_BYTES"])
min_rows = int(os.environ["MIN_ROWS"])
required = {"latitude", "longitude", "area_in_meters", "confidence", "geometry"}

if not target.is_file():
    raise SystemExit(f"missing download: {target}")
size = target.stat().st_size
if size <= 0:
    raise SystemExit(f"empty download: {target}")
if size > max_file_bytes:
    raise SystemExit(f"download exceeds cap: {size} > {max_file_bytes}")
head = target.read_bytes()[:512].lstrip().lower()
if head.startswith(b"<") or b"<html" in head:
    raise SystemExit(f"download looks like HTML, not gzip data: {target}")
if target.read_bytes()[:2] != b"\x1f\x8b":
    raise SystemExit(f"download is not gzip data: {target}")

rows = 0
sampled_geometry = 0
min_area = math.inf
max_area = 0.0
min_confidence = math.inf
max_confidence = -math.inf
with gzip.open(target, "rt", encoding="utf-8", errors="replace", newline="") as fh:
    reader = csv.DictReader(fh)
    if reader.fieldnames is None:
        raise SystemExit("missing Open Buildings CSV header")
    fieldnames = {field.strip() for field in reader.fieldnames}
    missing = sorted(required - fieldnames)
    if missing:
        raise SystemExit(f"missing required fields: {missing}; header={reader.fieldnames}")
    for row in reader:
        rows += 1
        if rows <= 1000:
            lat = float(row["latitude"])
            lon = float(row["longitude"])
            area = float(row["area_in_meters"])
            confidence = float(row["confidence"])
            geometry = row["geometry"]
            if not (-90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0):
                raise SystemExit(f"bad centroid near row {rows}: {lat},{lon}")
            if not (math.isfinite(area) and area > 0.0):
                raise SystemExit(f"bad area near row {rows}: {area}")
            if not (0.0 <= confidence <= 1.0):
                raise SystemExit(f"bad confidence near row {rows}: {confidence}")
            if not (
                geometry.startswith("POLYGON((")
                or geometry.startswith("POLYGON ((")
                or geometry.startswith("MULTIPOLYGON(((")
                or geometry.startswith("MULTIPOLYGON (((")
            ):
                raise SystemExit(f"unexpected geometry near row {rows}: {geometry[:64]!r}")
            sampled_geometry += 1
            min_area = min(min_area, area)
            max_area = max(max_area, area)
            min_confidence = min(min_confidence, confidence)
            max_confidence = max(max_confidence, confidence)

if rows < min_rows:
    raise SystemExit(f"too few Open Buildings rows: {rows} < {min_rows}")
if sampled_geometry == 0:
    raise SystemExit("no geometry rows sampled")

inventory = {
    "dataset_id": "google_open_buildings_v3_s2_073_geometry_f32",
    "url": os.environ["URL"],
    "archive_file": target.name,
    "archive_bytes": size,
    "rows": rows,
    "sampled_geometry_rows": sampled_geometry,
    "min_area_in_meters_sample": min_area,
    "max_area_in_meters_sample": max_area,
    "min_confidence_sample": min_confidence,
    "max_confidence_sample": max_confidence,
    "max_file_bytes": max_file_bytes,
}
(download_dir / "download_inventory.json").write_text(
    json.dumps(inventory, indent=2, sort_keys=True) + "\n",
    encoding="utf-8",
)
print(
    f"semantic_validation=ok rows={rows} archive_bytes={size} "
    f"sample_area=[{min_area},{max_area}] sample_confidence=[{min_confidence},{max_confidence}]"
)
PY

echo "[$(date -Is)] download done dataset=$DATASET_ID"
