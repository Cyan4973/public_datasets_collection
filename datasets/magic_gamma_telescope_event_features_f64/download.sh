#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="magic_gamma_telescope_event_features_f64"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
DOWNLOAD_DIR="$REPO_ROOT/$DATA_DIR/downloads/$DATASET_ID"
mkdir -p "$LOG_DIR" "$DOWNLOAD_DIR"

RUN_TS="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="$LOG_DIR/download.$RUN_TS.log"
LATEST_LOG="$LOG_DIR/download.latest.log"
exec > >(tee "$LOG_FILE" "$LATEST_LOG") 2>&1

echo "[$(date -Is)] download start dataset=$DATASET_ID"

URL="${MAGIC_URL:-https://archive.ics.uci.edu/ml/machine-learning-databases/magic/magic04.data}"
TARGET="$DOWNLOAD_DIR/magic04.data"
PLAN="$DOWNLOAD_DIR/download_plan.tsv"
MIN_ROWS="${MAGIC_MIN_ROWS:-15000}"
MAX_FILE_BYTES="${MAGIC_MAX_FILE_BYTES:-5000000}"

printf 'resource_id\turl\tfile\nmagic04_data\t%s\t%s\n' "$URL" "$(basename "$TARGET")" > "$PLAN"

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
import json
import os
from pathlib import Path

target = Path(os.environ["TARGET"])
download_dir = Path(os.environ["DOWNLOAD_DIR"])
min_rows = int(os.environ["MIN_ROWS"])
max_file_bytes = int(os.environ["MAX_FILE_BYTES"])
if not target.is_file():
    raise SystemExit(f"missing download: {target}")
if target.stat().st_size > max_file_bytes:
    raise SystemExit(f"download exceeds cap: {target.stat().st_size}")
rows = 0
bad_rows = 0
with target.open("r", encoding="utf-8", errors="replace", newline="") as fh:
    for record in csv.reader(fh):
        if len(record) != 11:
            bad_rows += 1
            continue
        try:
            [float(value) for value in record[:10]]
        except ValueError:
            bad_rows += 1
            continue
        if record[10] not in {"g", "h"}:
            bad_rows += 1
            continue
        rows += 1
if rows < min_rows:
    raise SystemExit(f"too few MAGIC rows: {rows} < {min_rows}")
if bad_rows:
    raise SystemExit(f"bad row count: {bad_rows}")
inventory = {
    "dataset_id": "magic_gamma_telescope_event_features_f64",
    "url": os.environ["URL"],
    "file": target.name,
    "source_bytes": target.stat().st_size,
    "rows": rows,
}
(download_dir / "download_inventory.json").write_text(
    json.dumps(inventory, indent=2, sort_keys=True) + "\n",
    encoding="utf-8",
)
print(f"semantic_validation=ok rows={rows} source_bytes={target.stat().st_size}")
PY

echo "[$(date -Is)] download done dataset=$DATASET_ID"
