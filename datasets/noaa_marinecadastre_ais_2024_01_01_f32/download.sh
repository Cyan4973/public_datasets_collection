#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="noaa_marinecadastre_ais_2024_01_01_f32"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
DOWNLOAD_DIR="$REPO_ROOT/$DATA_DIR/downloads/$DATASET_ID"
mkdir -p "$LOG_DIR" "$DOWNLOAD_DIR"

RUN_TS="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="$LOG_DIR/download.$RUN_TS.log"
LATEST_LOG="$LOG_DIR/download.latest.log"
exec > >(tee "$LOG_FILE" "$LATEST_LOG") 2>&1

echo "[$(date -Is)] download start dataset=$DATASET_ID"

URL="${NOAA_AIS_URL:-https://coast.noaa.gov/htdata/CMSP/AISDataHandler/2024/AIS_2024_01_01.zip}"
TARGET="$DOWNLOAD_DIR/AIS_2024_01_01.zip"
PLAN="$DOWNLOAD_DIR/download_plan.tsv"
MAX_FILE_BYTES="${NOAA_AIS_MAX_FILE_BYTES:-800000000}"
HARD_MAX_FILE_BYTES=1000000000
MIN_ROWS="${NOAA_AIS_MIN_ROWS:-1000000}"

if (( MAX_FILE_BYTES > HARD_MAX_FILE_BYTES )); then
  echo "requested max file size $MAX_FILE_BYTES exceeds hard cap $HARD_MAX_FILE_BYTES; clamping"
  MAX_FILE_BYTES="$HARD_MAX_FILE_BYTES"
fi

printf 'resource_id\turl\tfile\nnoaa_ais_daily_zip\t%s\t%s\n' "$URL" "$(basename "$TARGET")" > "$PLAN"

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
import io
import json
import os
import zipfile
from pathlib import Path

REQUIRED_FIELDS = {"MMSI", "BASEDATETIME", "LAT", "LON", "SOG", "COG", "HEADING"}

target = Path(os.environ["TARGET"])
download_dir = Path(os.environ["DOWNLOAD_DIR"])
max_file_bytes = int(os.environ["MAX_FILE_BYTES"])
min_rows = int(os.environ["MIN_ROWS"])
if not target.is_file():
    raise SystemExit(f"missing download: {target}")
size = target.stat().st_size
if size <= 0:
    raise SystemExit(f"empty download: {target}")
if size > max_file_bytes:
    raise SystemExit(f"download exceeds cap: {size} > {max_file_bytes}")
head = target.read_bytes()[:256].lstrip().lower()
if head.startswith(b"<") or b"<html" in head:
    raise SystemExit(f"download looks like HTML, not ZIP: {target}")

with zipfile.ZipFile(target) as zf:
    members = [name for name in zf.namelist() if name.lower().endswith(".csv")]
    if len(members) != 1:
        raise SystemExit(f"expected exactly one CSV member, found {members}")
    member = members[0]
    info = zf.getinfo(member)
    with zf.open(member) as raw:
        text = io.TextIOWrapper(raw, encoding="utf-8-sig", errors="replace", newline="")
        reader = csv.reader(text)
        try:
            header = [field.strip() for field in next(reader)]
        except StopIteration:
            raise SystemExit(f"empty CSV member: {member}") from None
        upper_header = {field.upper() for field in header}
        missing = sorted(REQUIRED_FIELDS - upper_header)
        if missing:
            raise SystemExit(f"missing required AIS fields: {missing}")
        width = len(header)
        rows = 0
        bad_width = 0
        for record in reader:
            if not record or all(not cell.strip() for cell in record):
                continue
            if len(record) != width:
                bad_width += 1
                continue
            rows += 1

if rows < min_rows:
    raise SystemExit(f"too few AIS rows: {rows} < {min_rows}")
if bad_width:
    raise SystemExit(f"bad row width count: {bad_width}")

inventory = {
    "dataset_id": "noaa_marinecadastre_ais_2024_01_01_f32",
    "url": os.environ["URL"],
    "archive_file": target.name,
    "archive_bytes": size,
    "max_file_bytes": max_file_bytes,
    "csv_member": member,
    "csv_rows": rows,
    "csv_columns": width,
    "csv_uncompressed_bytes": info.file_size,
}
(download_dir / "download_inventory.json").write_text(
    json.dumps(inventory, indent=2, sort_keys=True) + "\n",
    encoding="utf-8",
)
print(
    f"semantic_validation=ok rows={rows} columns={width} "
    f"archive_bytes={size} csv_bytes={info.file_size}"
)
PY

echo "[$(date -Is)] download done dataset=$DATASET_ID"
