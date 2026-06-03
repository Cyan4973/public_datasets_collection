#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="nyc_311_descriptor_u16"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
DOWNLOAD_DIR="$REPO_ROOT/$DATA_DIR/downloads/$DATASET_ID"
mkdir -p "$LOG_DIR" "$DOWNLOAD_DIR"

RUN_TS="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="$LOG_DIR/download.$RUN_TS.log"
LATEST_LOG="$LOG_DIR/download.latest.log"
exec > >(tee "$LOG_FILE" "$LATEST_LOG") 2>&1

echo "[$(date -Is)] download start dataset=$DATASET_ID"

OUT="$DOWNLOAD_DIR/nyc_311_jan_2024_descriptor.csv"
URL="https://data.cityofnewyork.us/resource/erm2-nwe9.csv?\$select=unique_key,descriptor&\$where=created_date%20%3E%3D%20'2024-01-01T00:00:00'%20AND%20created_date%20%3C%20'2024-02-01T00:00:00'&\$order=unique_key&\$limit=5000000"

if [ -s "$OUT" ]; then
  bytes="$(wc -c < "$OUT" | tr -d ' ')"
  echo "cached csv bytes=$bytes"
else
  curl -fL --retry 3 --retry-delay 2 \
    -H "User-Agent: Mozilla/5.0 (openzl dataset collection)" \
    -o "$OUT" "$URL"
fi

test -s "$OUT"
python3 - <<'PY' "$OUT"
import csv, sys
path = sys.argv[1]
with open(path, "r", encoding="utf-8", newline="") as f:
    reader = csv.DictReader(f)
    if reader.fieldnames != ["unique_key", "descriptor"]:
        raise SystemExit(f"unexpected CSV header: {reader.fieldnames}")
    row_count = 0
    for row in reader:
        if "unique_key" not in row or "descriptor" not in row:
            raise SystemExit("missing expected columns")
        row_count += 1
    if row_count == 0:
        raise SystemExit("CSV contains zero rows")
    print(f"validated_rows={row_count}")
PY

echo "[$(date -Is)] download done dataset=$DATASET_ID"
