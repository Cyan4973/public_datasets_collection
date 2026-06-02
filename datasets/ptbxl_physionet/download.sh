#!/usr/bin/env bash
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="ptbxl_physionet"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
DOWNLOAD_DIR="$REPO_ROOT/$DATA_DIR/downloads/$DATASET_ID"
FILTER_DIR="$REPO_ROOT/$DATA_DIR/filtered/$DATASET_ID"
mkdir -p "$LOG_DIR" "$DOWNLOAD_DIR" "$FILTER_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="$LOG_DIR/download.$RUN_TS.log"
LATEST_LOG="$LOG_DIR/download.latest.log"
FAILURES="$DOWNLOAD_DIR/download_failures.tsv"
exec > >(tee "$LOG_FILE" "$LATEST_LOG") 2>&1
echo "[$(date -Is)] download start dataset=$DATASET_ID"

BASE_URLS=(
  "https://physionet.org/files/ptb-xl/1.0.3"
  "https://www.physionet.org/files/ptb-xl/1.0.3"
)
PTBXL_RECORDS_PER_FOLD="${PTBXL_RECORDS_PER_FOLD:-20}"
FULL_DATASET="${FULL_DATASET:-0}"
MAX_RECORDS="${MAX_RECORDS:-}"
printf 'path\turl\n' > "$FAILURES"
failure_count=0

download_required() {
  local rel="$1"
  local out="$2"
  if [ -f "$out" ]; then
    echo "cache_hit path=$rel"
    return 0
  fi
  local ok=0
  for base in "${BASE_URLS[@]}"; do
    local url="${base}/${rel}"
    echo "fetch path=$rel url=$url"
    if curl -fL --retry 3 --retry-delay 5 -o "$out" "$url"; then
      ok=1
      break
    fi
  done
  if [ "$ok" -ne 1 ]; then
    printf '%s\t%s\n' "$rel" "${BASE_URLS[0]}/${rel}" >> "$FAILURES"
    failure_count=$((failure_count + 1))
    return 1
  fi
}

download_optional() {
  local rel="$1"
  local out="$2"
  if [ -f "$out" ]; then
    return 0
  fi
  for base in "${BASE_URLS[@]}"; do
    local url="${base}/${rel}"
    if curl -fL --retry 2 --retry-delay 2 -o "$out" "$url"; then
      return 0
    fi
  done
  rm -f "$out"
  return 0
}

download_required "ptbxl_database.csv" "$DOWNLOAD_DIR/ptbxl_database.csv"
download_required "scp_statements.csv" "$DOWNLOAD_DIR/scp_statements.csv"
download_optional "README.md" "$DOWNLOAD_DIR/README.md"
download_optional "LICENSE.txt" "$DOWNLOAD_DIR/LICENSE.txt"

DOWNLOAD_DIR="$DOWNLOAD_DIR" FULL_DATASET="$FULL_DATASET" PTBXL_RECORDS_PER_FOLD="$PTBXL_RECORDS_PER_FOLD" MAX_RECORDS="$MAX_RECORDS" python3 - <<'PY'
import csv
import os
from pathlib import Path

download_dir = Path(os.environ["DOWNLOAD_DIR"])
csv_path = download_dir / "ptbxl_database.csv"
full_dataset = os.environ["FULL_DATASET"].strip().lower() in {"1", "true", "yes"}
per_fold = int(os.environ["PTBXL_RECORDS_PER_FOLD"])
if per_fold <= 0:
    raise SystemExit("PTBXL_RECORDS_PER_FOLD must be positive")
with csv_path.open("r", encoding="utf-8", newline="") as f:
    reader = csv.DictReader(f)
    fieldnames = reader.fieldnames or []
    if "filename_lr" not in fieldnames:
        raise SystemExit("ptbxl_database.csv missing filename_lr")
    if not full_dataset and "strat_fold" not in fieldnames:
        raise SystemExit("ptbxl_database.csv missing strat_fold")
    seen = set()
    counts = {}
    records = []
    for row in reader:
        rel = (row.get("filename_lr") or "").strip()
        if not rel or rel in seen:
            continue
        if not full_dataset:
            fold = (row.get("strat_fold") or "").strip()
            if not fold:
                continue
            count = counts.get(fold, 0)
            if count >= per_fold:
                continue
            counts[fold] = count + 1
        seen.add(rel)
        records.append(rel)
if os.environ["MAX_RECORDS"]:
    max_records = int(os.environ["MAX_RECORDS"])
    if max_records <= 0:
        raise SystemExit("MAX_RECORDS must be positive")
    records = records[:max_records]
if not records:
    raise SystemExit("no low-resolution records selected")
(download_dir / "RECORDS.selected").write_text("\n".join(records) + "\n", encoding="utf-8")
print(f"selected_records={len(records)}")
PY

while IFS= read -r rel; do
  [ -n "$rel" ] || continue
  mkdir -p "$(dirname "$DOWNLOAD_DIR/$rel")"
  download_required "${rel}.hea" "$DOWNLOAD_DIR/${rel}.hea"
  download_required "${rel}.dat" "$DOWNLOAD_DIR/${rel}.dat"
done < "$DOWNLOAD_DIR/RECORDS.selected"

selected_records=$(wc -l < "$DOWNLOAD_DIR/RECORDS.selected" | tr -d ' ')
printf 'selected_records\n%s\n' "$selected_records" > "$FILTER_DIR/download_inventory.tsv"
echo "selected_records=$selected_records failure_count=$failure_count"
if [ "$failure_count" -ne 0 ]; then
  echo "[$(date -Is)] download failed dataset=$DATASET_ID"
  exit 1
fi
echo "[$(date -Is)] download done dataset=$DATASET_ID"
