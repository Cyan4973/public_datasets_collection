#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="uci_steel_plates_faults_features_f64"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
DOWNLOAD_DIR="$REPO_ROOT/$DATA_DIR/downloads/$DATASET_ID"
mkdir -p "$LOG_DIR" "$DOWNLOAD_DIR"

RUN_TS="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="$LOG_DIR/download.$RUN_TS.log"
LATEST_LOG="$LOG_DIR/download.latest.log"
exec > >(tee "$LOG_FILE" "$LATEST_LOG") 2>&1

echo "[$(date -Is)] download start dataset=$DATASET_ID"

URL="${UCI_STEEL_PLATES_URL:-https://archive.ics.uci.edu/ml/machine-learning-databases/00198/Faults.NNA}"
TARGET="$DOWNLOAD_DIR/Faults.NNA"
PLAN="$DOWNLOAD_DIR/download_plan.tsv"
MIN_ROWS="${UCI_STEEL_PLATES_MIN_ROWS:-1900}"
MAX_FILE_BYTES="${UCI_STEEL_PLATES_MAX_FILE_BYTES:-5000000}"

printf 'resource_id\turl\tfile\nfaults_nna\t%s\t%s\n' "$URL" "$(basename "$TARGET")" > "$PLAN"

if [[ -s "$TARGET" && "${FORCE_DOWNLOAD:-0}" != "1" ]]; then
  echo "cache_hit path=$TARGET"
else
  echo "fetch url=$URL"
  curl --globoff -fL --retry 3 --retry-delay 5 --max-filesize "$MAX_FILE_BYTES" \
    -A "openzl-public-datasets/1.0 (numeric dataset collection)" \
    -o "$TARGET.tmp" "$URL"
  mv "$TARGET.tmp" "$TARGET"
fi

export TARGET DOWNLOAD_DIR URL MIN_ROWS MAX_FILE_BYTES
python3 - <<'PY'
from __future__ import annotations

import json
import os
from pathlib import Path

EXPECTED_COLUMNS = 34
FEATURE_COLUMNS = 27
LABEL_COLUMNS = 7

target = Path(os.environ["TARGET"])
download_dir = Path(os.environ["DOWNLOAD_DIR"])
min_rows = int(os.environ["MIN_ROWS"])
max_file_bytes = int(os.environ["MAX_FILE_BYTES"])
if not target.is_file():
    raise SystemExit(f"missing download: {target}")
size = target.stat().st_size
if size <= 0:
    raise SystemExit(f"empty download: {target}")
if size > max_file_bytes:
    raise SystemExit(f"download exceeds cap: {size}")
head = target.read_bytes()[:256].lstrip().lower()
if head.startswith(b"<") or b"<html" in head:
    raise SystemExit(f"download looks like HTML, not numeric data: {target}")

rows = 0
bad_width = 0
bad_numeric = 0
bad_label = 0
feature_nonzero = [0] * FEATURE_COLUMNS
with target.open("r", encoding="utf-8", errors="replace") as fh:
    for line in fh:
        line = line.strip()
        if not line:
            continue
        parts = line.split()
        if len(parts) != EXPECTED_COLUMNS:
            bad_width += 1
            continue
        try:
            values = [float(part) for part in parts]
        except ValueError:
            bad_numeric += 1
            continue
        labels = values[FEATURE_COLUMNS:]
        if len(labels) != LABEL_COLUMNS or any(label not in (0.0, 1.0) for label in labels) or sum(labels) != 1.0:
            bad_label += 1
            continue
        for index, value in enumerate(values[:FEATURE_COLUMNS]):
            if value != 0.0:
                feature_nonzero[index] += 1
        rows += 1

if rows < min_rows:
    raise SystemExit(f"too few valid rows: {rows} < {min_rows}")
if bad_width or bad_numeric or bad_label:
    raise SystemExit(
        f"invalid rows width={bad_width} numeric={bad_numeric} label={bad_label}"
    )
empty_features = [index for index, count in enumerate(feature_nonzero) if count == 0]
if empty_features:
    raise SystemExit(f"all-zero feature columns: {empty_features}")

inventory = {
    "dataset_id": "uci_steel_plates_faults_features_f64",
    "url": os.environ["URL"],
    "file": target.name,
    "bytes": size,
    "rows": rows,
    "columns": EXPECTED_COLUMNS,
    "feature_columns": FEATURE_COLUMNS,
    "label_columns": LABEL_COLUMNS,
}
(download_dir / "download_inventory.json").write_text(
    json.dumps(inventory, indent=2, sort_keys=True) + "\n",
    encoding="utf-8",
)
print(
    f"semantic_validation=ok rows={rows} columns={EXPECTED_COLUMNS} "
    f"feature_columns={FEATURE_COLUMNS} bytes={size}"
)
PY

echo "[$(date -Is)] download done dataset=$DATASET_ID"
