#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="hsl_gtfs_static_schedule_numeric"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
DOWNLOAD_DIR="$REPO_ROOT/$DATA_DIR/downloads/$DATASET_ID"
mkdir -p "$LOG_DIR" "$DOWNLOAD_DIR"

RUN_TS="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="$LOG_DIR/download.$RUN_TS.log"
LATEST_LOG="$LOG_DIR/download.latest.log"
exec > >(tee "$LOG_FILE" "$LATEST_LOG") 2>&1

echo "[$(date -Is)] download start dataset=$DATASET_ID"

GTFS_URL="${HSL_GTFS_URL:-https://infopalvelut.storage.hsldev.com/gtfs/hsl.zip}"
MAX_FILE_BYTES="${HSL_GTFS_MAX_FILE_BYTES:-300000000}"
MAX_UNCOMPRESSED_BYTES="${HSL_GTFS_MAX_UNCOMPRESSED_BYTES:-1500000000}"
UA="openzl-public-datasets/1.0 (numeric dataset collection)"
ZIP_PATH="$DOWNLOAD_DIR/hsl_gtfs.zip"

if [ -s "$ZIP_PATH" ] && [ "${FORCE_DOWNLOAD:-0}" != "1" ]; then
  bytes="$(wc -c < "$ZIP_PATH" | tr -d ' ')"
  echo "gtfs cache_hit bytes=$bytes path=$ZIP_PATH"
else
  echo "fetch_gtfs url=$GTFS_URL"
  curl --globoff -fL --retry 5 --retry-delay 5 --max-filesize "$MAX_FILE_BYTES" \
    --speed-limit 1024 --speed-time 180 \
    -A "$UA" -o "$ZIP_PATH.tmp" "$GTFS_URL"
  mv "$ZIP_PATH.tmp" "$ZIP_PATH"
  bytes="$(wc -c < "$ZIP_PATH" | tr -d ' ')"
  echo "gtfs downloaded bytes=$bytes"
fi

if [ "$bytes" -gt "$MAX_FILE_BYTES" ]; then
  echo "GTFS ZIP exceeds cap: $bytes > $MAX_FILE_BYTES" >&2
  exit 1
fi

export DATASET_ID GTFS_URL ZIP_PATH DOWNLOAD_DIR MAX_UNCOMPRESSED_BYTES
python3 - <<'PY'
from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import zipfile
from pathlib import Path

zip_path = Path(os.environ["ZIP_PATH"])
download_dir = Path(os.environ["DOWNLOAD_DIR"])
required = {
    "stop_times.txt": {"arrival_time", "departure_time", "stop_sequence"},
    "stops.txt": {"stop_lat", "stop_lon"},
    "shapes.txt": {"shape_pt_lat", "shape_pt_lon", "shape_pt_sequence"},
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def open_text(zf: zipfile.ZipFile, name: str):
    return io.TextIOWrapper(zf.open(name), encoding="utf-8-sig", newline="")


def count_rows_and_columns(zf: zipfile.ZipFile, name: str) -> tuple[int, set[str]]:
    with open_text(zf, name) as fh:
        reader = csv.DictReader(fh)
        columns = set(reader.fieldnames or [])
        rows = sum(1 for _ in reader)
    return rows, columns


def parse_time(value: str) -> int:
    parts = value.split(":")
    if len(parts) != 3:
        raise ValueError(value)
    h, m, s = (int(part) for part in parts)
    if h < 0 or not (0 <= m < 60) or not (0 <= s < 60):
        raise ValueError(value)
    return h * 3600 + m * 60 + s


def first_parseable_stop_times(zf: zipfile.ZipFile) -> int:
    parsed = 0
    with open_text(zf, "stop_times.txt") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            if parsed >= 1000:
                break
            parse_time(row["arrival_time"])
            parse_time(row["departure_time"])
            seq = int(row["stop_sequence"])
            if seq < 0:
                raise ValueError("negative stop_sequence")
            parsed += 1
    return parsed


with zipfile.ZipFile(zip_path) as zf:
    infos = zf.infolist()
    names = {info.filename for info in infos if not info.is_dir()}
    uncompressed_bytes = sum(info.file_size for info in infos)
    if uncompressed_bytes > int(os.environ["MAX_UNCOMPRESSED_BYTES"]):
        raise SystemExit(
            f"GTFS ZIP uncompressed bytes exceed cap: {uncompressed_bytes}"
        )
    table_stats = {}
    for name, needed in required.items():
        if name not in names:
            raise SystemExit(f"missing required GTFS table: {name}")
        row_count, columns = count_rows_and_columns(zf, name)
        missing = needed - columns
        if missing:
            raise SystemExit(f"{name}: missing required columns {sorted(missing)}")
        if row_count < 1000:
            raise SystemExit(f"{name}: too few rows for this recipe: {row_count}")
        table_stats[name] = {
            "row_count": row_count,
            "columns": sorted(columns),
            "compressed_bytes": zf.getinfo(name).compress_size,
            "uncompressed_bytes": zf.getinfo(name).file_size,
        }
    parsed_stop_times = first_parseable_stop_times(zf)
    if parsed_stop_times < 1000:
        raise SystemExit("stop_times.txt did not contain 1000 parseable rows")
    if "frequencies.txt" in names:
        rows, columns = count_rows_and_columns(zf, "frequencies.txt")
        table_stats["frequencies.txt"] = {
            "row_count": rows,
            "columns": sorted(columns),
            "compressed_bytes": zf.getinfo("frequencies.txt").compress_size,
            "uncompressed_bytes": zf.getinfo("frequencies.txt").file_size,
        }

inventory = {
    "dataset_id": os.environ["DATASET_ID"],
    "gtfs_url": os.environ["GTFS_URL"],
    "zip_local_path": str(zip_path.relative_to(download_dir)),
    "zip_bytes": zip_path.stat().st_size,
    "zip_sha256": sha256_file(zip_path),
    "uncompressed_bytes": uncompressed_bytes,
    "table_stats": table_stats,
}
(download_dir / "download_inventory.json").write_text(
    json.dumps(inventory, indent=2, sort_keys=True) + "\n",
    encoding="utf-8",
)
print(
    "semantic_validation=ok "
    f"zip_bytes={zip_path.stat().st_size} "
    f"uncompressed_bytes={uncompressed_bytes} "
    f"tables={sorted(table_stats)}"
)
PY

echo "[$(date -Is)] download done dataset=$DATASET_ID"
