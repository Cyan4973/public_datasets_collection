#!/usr/bin/env bash
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="chbmit_physionet"
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
  "https://physionet.org/files/chbmit/1.0.0"
  "https://archive.physionet.org/pn6/chbmit"
)
CHBMIT_CASES="${CHBMIT_CASES:-3}"
CHBMIT_RECORDS_PER_CASE="${CHBMIT_RECORDS_PER_CASE:-3}"
FULL_DATASET="${FULL_DATASET:-0}"
MAX_RECORDS="${MAX_RECORDS:-}"

printf 'path\turl\n' > "$FAILURES"
failure_count=0

fetch_required() {
  local rel="$1"
  local out="$DOWNLOAD_DIR/$rel"
  local tmp="${out}.tmp"
  mkdir -p "$(dirname "$out")"
  if [ -f "$out" ]; then
    echo "cache_hit path=$rel"
    return 0
  fi
  for base in "${BASE_URLS[@]}"; do
    local url="${base}/${rel}"
    echo "fetch path=$rel url=$url"
    if curl -fL --retry 3 --retry-delay 5 -o "$tmp" "$url"; then
      mv "$tmp" "$out"
      return 0
    fi
    rm -f "$tmp"
  done
  printf '%s\t%s\n' "$rel" "${BASE_URLS[0]}/${rel}" >> "$FAILURES"
  failure_count=$((failure_count + 1))
  return 1
}

fetch_optional() {
  local rel="$1"
  local out="$DOWNLOAD_DIR/$rel"
  local tmp="${out}.tmp"
  mkdir -p "$(dirname "$out")"
  if [ -f "$out" ]; then
    return 0
  fi
  for base in "${BASE_URLS[@]}"; do
    local url="${base}/${rel}"
    if curl -fL --retry 2 --retry-delay 3 -o "$tmp" "$url"; then
      mv "$tmp" "$out"
      return 0
    fi
    rm -f "$tmp"
  done
  return 0
}

fetch_required "RECORDS"
fetch_required "SUBJECT-INFO"
fetch_optional "RECORDS-WITH-SEIZURES"
fetch_optional "README"
fetch_optional "SHA256SUMS"

DOWNLOAD_DIR="$DOWNLOAD_DIR" FULL_DATASET="$FULL_DATASET" CHBMIT_CASES="$CHBMIT_CASES" CHBMIT_RECORDS_PER_CASE="$CHBMIT_RECORDS_PER_CASE" MAX_RECORDS="$MAX_RECORDS" python3 - <<'PY'
from collections import OrderedDict
from pathlib import Path
import os

download_dir = Path(os.environ["DOWNLOAD_DIR"])
full_dataset = os.environ["FULL_DATASET"] == "1"
case_limit = int(os.environ["CHBMIT_CASES"])
records_per_case = int(os.environ["CHBMIT_RECORDS_PER_CASE"])
max_records = int(os.environ["MAX_RECORDS"]) if os.environ["MAX_RECORDS"] else None

records = [
    line.strip() for line in (download_dir / "RECORDS").read_text(encoding="utf-8").splitlines()
    if line.strip().endswith(".edf")
]
if not records:
    raise SystemExit("RECORDS does not contain EDF paths")
by_case = OrderedDict()
for rel in records:
    case = rel.split("/", 1)[0]
    by_case.setdefault(case, []).append(rel)

if full_dataset:
    selected = list(records)
else:
    if case_limit <= 0 or records_per_case <= 0:
        raise SystemExit("CHBMIT_CASES and CHBMIT_RECORDS_PER_CASE must be positive")
    selected = []
    for case, case_records in list(by_case.items())[:case_limit]:
        if len(case_records) < records_per_case:
            raise SystemExit(f"{case} has only {len(case_records)} records")
        selected.extend(case_records[:records_per_case])
if max_records is not None:
    if max_records <= 0:
        raise SystemExit("MAX_RECORDS must be positive")
    selected = selected[:max_records]

selected_cases = []
seen = set()
for rel in selected:
    case = rel.split("/", 1)[0]
    if case not in seen:
        seen.add(case)
        selected_cases.append(case)

(download_dir / "RECORDS.selected").write_text("\n".join(selected) + "\n", encoding="utf-8")
(download_dir / "CASES.selected").write_text("\n".join(selected_cases) + "\n", encoding="utf-8")
print(f"selected_cases={len(selected_cases)} selected_records={len(selected)}")
PY

while IFS= read -r case; do
  [ -n "$case" ] || continue
  fetch_required "${case}/${case}-summary.txt"
done < "$DOWNLOAD_DIR/CASES.selected"

while IFS= read -r rel; do
  [ -n "$rel" ] || continue
  fetch_required "$rel"
done < "$DOWNLOAD_DIR/RECORDS.selected"

selected_records=$(wc -l < "$DOWNLOAD_DIR/RECORDS.selected" | tr -d ' ')
selected_cases=$(wc -l < "$DOWNLOAD_DIR/CASES.selected" | tr -d ' ')
printf 'selected_cases\tselected_records\n%s\t%s\n' "$selected_cases" "$selected_records" > "$FILTER_DIR/download_inventory.tsv"
echo "selected_cases=$selected_cases selected_records=$selected_records failure_count=$failure_count"

if [ "$failure_count" -ne 0 ]; then
  echo "[$(date -Is)] download failed dataset=$DATASET_ID"
  exit 1
fi
echo "[$(date -Is)] download done dataset=$DATASET_ID"
