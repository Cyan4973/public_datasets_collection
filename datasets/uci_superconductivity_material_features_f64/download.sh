#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="uci_superconductivity_material_features_f64"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
DOWNLOAD_DIR="$REPO_ROOT/$DATA_DIR/downloads/$DATASET_ID"
mkdir -p "$LOG_DIR" "$DOWNLOAD_DIR"

RUN_TS="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="$LOG_DIR/download.$RUN_TS.log"
LATEST_LOG="$LOG_DIR/download.latest.log"
exec > >(tee "$LOG_FILE" "$LATEST_LOG") 2>&1

echo "[$(date -Is)] download start dataset=$DATASET_ID"

URL="${SUPERCONDUCTIVITY_URL:-https://archive.ics.uci.edu/ml/machine-learning-databases/00464/superconduct.zip}"
TARGET="$DOWNLOAD_DIR/superconduct.zip"
PLAN="$DOWNLOAD_DIR/download_plan.tsv"
MIN_ROWS="${SUPERCONDUCTIVITY_MIN_ROWS:-20000}"
MAX_FILE_BYTES="${SUPERCONDUCTIVITY_MAX_FILE_BYTES:-20000000}"

printf 'resource_id\turl\tfile\nsuperconduct_zip\t%s\t%s\n' "$URL" "$(basename "$TARGET")" > "$PLAN"

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

import csv
import io
import json
import os
import zipfile
from pathlib import Path

target = Path(os.environ["TARGET"])
download_dir = Path(os.environ["DOWNLOAD_DIR"])
min_rows = int(os.environ["MIN_ROWS"])
max_file_bytes = int(os.environ["MAX_FILE_BYTES"])
if not target.is_file():
    raise SystemExit(f"missing download: {target}")
if target.stat().st_size > max_file_bytes:
    raise SystemExit(f"download exceeds cap: {target.stat().st_size}")
with zipfile.ZipFile(target) as zf:
    train_names = [name for name in zf.namelist() if name.lower().endswith("train.csv")]
    if len(train_names) != 1:
        raise SystemExit(f"expected exactly one train.csv member, found {train_names}")
    info = zf.getinfo(train_names[0])
    with zf.open(info) as raw:
        text = io.TextIOWrapper(raw, encoding="utf-8-sig", errors="replace", newline="")
        reader = csv.reader(text)
        header = next(reader)
        rows = 0
        bad_width = 0
        for record in reader:
            if len(record) != len(header):
                bad_width += 1
                continue
            rows += 1
if rows < min_rows:
    raise SystemExit(f"too few training rows: {rows} < {min_rows}")
if bad_width:
    raise SystemExit(f"bad row width count: {bad_width}")
inventory = {
    "dataset_id": "uci_superconductivity_material_features_f64",
    "url": os.environ["URL"],
    "archive_file": target.name,
    "archive_bytes": target.stat().st_size,
    "train_member": train_names[0],
    "train_rows": rows,
    "train_columns": len(header),
    "train_uncompressed_bytes": info.file_size,
}
(download_dir / "download_inventory.json").write_text(
    json.dumps(inventory, indent=2, sort_keys=True) + "\n",
    encoding="utf-8",
)
print(
    f"semantic_validation=ok rows={rows} columns={len(header)} "
    f"archive_bytes={target.stat().st_size}"
)
PY

echo "[$(date -Is)] download done dataset=$DATASET_ID"
