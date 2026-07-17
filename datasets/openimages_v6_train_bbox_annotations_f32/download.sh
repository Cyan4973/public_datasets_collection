#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="openimages_v6_train_bbox_annotations_f32"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
DOWNLOAD_DIR="$REPO_ROOT/$DATA_DIR/downloads/$DATASET_ID"
mkdir -p "$LOG_DIR" "$DOWNLOAD_DIR"

RUN_TS="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="$LOG_DIR/download.$RUN_TS.log"
LATEST_LOG="$LOG_DIR/download.latest.log"
exec > >(tee "$LOG_FILE" "$LATEST_LOG") 2>&1

echo "[$(date -Is)] download start dataset=$DATASET_ID"

URL="${OPENIMAGES_BBOX_URL:-https://storage.googleapis.com/openimages/v6/oidv6-train-annotations-bbox.csv}"
TARGET="$DOWNLOAD_DIR/oidv6-train-annotations-bbox.range.csv"
PLAN="$DOWNLOAD_DIR/download_plan.tsv"
RANGE_BYTES="${OPENIMAGES_BBOX_RANGE_BYTES:-900000000}"
HARD_MAX_BYTES=1000000000
MIN_ROWS="${OPENIMAGES_BBOX_MIN_ROWS:-3000000}"

if (( RANGE_BYTES > HARD_MAX_BYTES )); then
  echo "requested range bytes $RANGE_BYTES exceeds hard cap $HARD_MAX_BYTES; clamping"
  RANGE_BYTES="$HARD_MAX_BYTES"
fi
if (( RANGE_BYTES < 1000000 )); then
  echo "range bytes too small: $RANGE_BYTES" >&2
  exit 1
fi
RANGE_END=$((RANGE_BYTES - 1))

printf 'resource_id\turl\tfile\trange\nopenimages_v6_train_bbox_csv_prefix\t%s\t%s\t0-%s\n' \
  "$URL" "$(basename "$TARGET")" "$RANGE_END" > "$PLAN"

if [[ -s "$TARGET" && "${FORCE_DOWNLOAD:-0}" != "1" ]]; then
  echo "cache_hit path=$TARGET"
else
  echo "fetch url=$URL range=0-$RANGE_END"
  curl --globoff -fL --retry 3 --retry-delay 5 --range "0-$RANGE_END" \
    --max-filesize "$RANGE_BYTES" \
    -A "openzl-public-datasets/1.0 (numeric dataset collection)" \
    -o "$TARGET.tmp" "$URL"
  mv "$TARGET.tmp" "$TARGET"
fi

export TARGET DOWNLOAD_DIR URL RANGE_BYTES MIN_ROWS
python3 - <<'PY'
from __future__ import annotations

import csv
import json
import os
from pathlib import Path

target = Path(os.environ["TARGET"])
download_dir = Path(os.environ["DOWNLOAD_DIR"])
range_bytes = int(os.environ["RANGE_BYTES"])
min_rows = int(os.environ["MIN_ROWS"])

EXPECTED_HEADER = [
    "ImageID",
    "Source",
    "LabelName",
    "Confidence",
    "XMin",
    "XMax",
    "YMin",
    "YMax",
    "IsOccluded",
    "IsTruncated",
    "IsGroupOf",
    "IsDepiction",
    "IsInside",
    "XClick1X",
    "XClick2X",
    "XClick3X",
    "XClick4X",
    "XClick1Y",
    "XClick2Y",
    "XClick3Y",
    "XClick4Y",
]
BBOX_FLOAT_FIELDS = [3, 4, 5, 6, 7]
CLICK_FLOAT_FIELDS = [13, 14, 15, 16, 17, 18, 19, 20]
FLOAT_FIELDS = [*BBOX_FLOAT_FIELDS, *CLICK_FLOAT_FIELDS]
FLAG_FIELDS = [8, 9, 10, 11, 12]

if not target.is_file():
    raise SystemExit(f"missing download: {target}")
size = target.stat().st_size
if size <= 0:
    raise SystemExit(f"empty download: {target}")
if size > range_bytes:
    raise SystemExit(f"download exceeds requested range cap: {size} > {range_bytes}")
head = target.read_bytes()[:512].lstrip().lower()
if head.startswith(b"<") or b"<html" in head:
    raise SystemExit(f"download looks like HTML, not CSV data: {target}")

complete_rows = 0
skipped_partial_tail = 0
min_coord = 1.0
max_coord = 0.0
with target.open("rb") as raw:
    header_line = raw.readline()
    if not header_line:
        raise SystemExit("empty Open Images CSV prefix")
    header = next(csv.reader([header_line.decode("utf-8-sig", errors="strict").rstrip("\r\n")]))
    if header != EXPECTED_HEADER:
        raise SystemExit(f"unexpected header: {header}")
    for raw_line in raw:
        if not raw_line.endswith(b"\n"):
            skipped_partial_tail += 1
            continue
        line = raw_line.decode("utf-8", errors="strict").rstrip("\r\n")
        if not line:
            continue
        row = next(csv.reader([line]))
        if len(row) != len(EXPECTED_HEADER):
            raise SystemExit(f"unexpected row width near row {complete_rows + 2}: {len(row)}")
        bbox_values = [float(row[idx]) for idx in BBOX_FLOAT_FIELDS]
        click_values = [float(row[idx]) for idx in CLICK_FLOAT_FIELDS]
        for value in bbox_values:
            if not (0.0 <= value <= 1.0):
                raise SystemExit(f"bbox float field outside normalized range: {value}")
        for value in click_values:
            if not (-1.0 <= value <= 1.0):
                raise SystemExit(f"click float field outside sentinel/normalized range: {value}")
        if not (bbox_values[2] >= bbox_values[1] and bbox_values[4] >= bbox_values[3]):
            raise SystemExit(f"invalid bbox ordering near row {complete_rows + 2}: {bbox_values}")
        for idx in FLAG_FIELDS:
            if row[idx] not in {"-1", "0", "1"}:
                raise SystemExit(f"non-binary annotation flag near row {complete_rows + 2}: {row[idx]!r}")
        min_coord = min(min_coord, *bbox_values[1:], *click_values)
        max_coord = max(max_coord, *bbox_values[1:], *click_values)
        complete_rows += 1

if complete_rows < min_rows:
    raise SystemExit(f"too few complete Open Images rows: {complete_rows} < {min_rows}")
if skipped_partial_tail > 1:
    raise SystemExit(f"too many partial tail rows: {skipped_partial_tail}")

inventory = {
    "dataset_id": "openimages_v6_train_bbox_annotations_f32",
    "url": os.environ["URL"],
    "range": f"0-{range_bytes - 1}",
    "file": target.name,
    "bytes": size,
    "complete_rows": complete_rows,
    "skipped_partial_tail": skipped_partial_tail,
    "min_coordinate_seen": min_coord,
    "max_coordinate_seen": max_coord,
}
(download_dir / "download_inventory.json").write_text(
    json.dumps(inventory, indent=2, sort_keys=True) + "\n",
    encoding="utf-8",
)
print(
    f"semantic_validation=ok complete_rows={complete_rows} bytes={size} "
    f"skipped_partial_tail={skipped_partial_tail} coords=[{min_coord},{max_coord}]"
)
PY

echo "[$(date -Is)] download done dataset=$DATASET_ID"
