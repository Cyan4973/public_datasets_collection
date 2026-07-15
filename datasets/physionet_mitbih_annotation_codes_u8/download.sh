#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="physionet_mitbih_annotation_codes_u8"
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
  "https://physionet.org/files/mitdb/1.0.0"
  "https://www.physionet.org/files/mitdb/1.0.0"
)
REQUIRED_METADATA_FILES=("RECORDS" "ANNOTATORS")
OPTIONAL_METADATA_FILES=("README" "README.md" "README.txt")
printf 'path\turl\n' > "$FAILURES"
failure_count=0

download_one() {
  local rel="$1"
  local out="$2"
  if [ -f "$out" ] && [ "${FORCE_DOWNLOAD:-0}" != "1" ]; then
    echo "cache_hit path=$rel"
    return 0
  fi
  local ok=0
  for base in "${BASE_URLS[@]}"; do
    local url="${base}/${rel}"
    echo "fetch path=$rel url=$url"
    if curl -fsSL --retry 3 --retry-delay 2 -o "$out.tmp" "$url"; then
      mv "$out.tmp" "$out"
      ok=1
      break
    fi
  done
  rm -f "$out.tmp"
  if [ "$ok" -ne 1 ]; then
    printf '%s\t%s\n' "$rel" "${BASE_URLS[0]}/${rel}" >> "$FAILURES"
    failure_count=$((failure_count + 1))
    return 1
  fi
}

download_optional() {
  local rel="$1"
  local out="$2"
  if [ -f "$out" ] && [ "${FORCE_DOWNLOAD:-0}" != "1" ]; then
    echo "cache_hit path=$rel"
    return 0
  fi
  for base in "${BASE_URLS[@]}"; do
    local url="${base}/${rel}"
    echo "fetch_optional path=$rel url=$url"
    if curl -fsSL --retry 2 --retry-delay 2 -o "$out.tmp" "$url" 2>/dev/null; then
      mv "$out.tmp" "$out"
      return 0
    fi
  done
  rm -f "$out.tmp" "$out"
  echo "optional_missing path=$rel"
  return 0
}

for f in "${REQUIRED_METADATA_FILES[@]}"; do
  download_one "$f" "$DOWNLOAD_DIR/$f"
done
for f in "${OPTIONAL_METADATA_FILES[@]}"; do
  download_optional "$f" "$DOWNLOAD_DIR/$f"
done

mapfile -t RECORD_LIST < <(sed '/^\s*$/d' "$DOWNLOAD_DIR/RECORDS")
if [ "${#RECORD_LIST[@]}" -eq 0 ]; then
  echo "ERROR: RECORDS is empty" >&2
  exit 1
fi
if [ -n "${MAX_RECORDS:-}" ]; then
  if [[ "${MAX_RECORDS}" =~ ^[0-9]+$ ]] && [ "${MAX_RECORDS}" -gt 0 ]; then
    RECORD_LIST=("${RECORD_LIST[@]:0:${MAX_RECORDS}}")
  else
    echo "ERROR: MAX_RECORDS must be a positive integer" >&2
    exit 1
  fi
fi
printf '%s\n' "${RECORD_LIST[@]}" > "$DOWNLOAD_DIR/RECORDS.selected"

for rec in "${RECORD_LIST[@]}"; do
  download_one "${rec}.atr" "$DOWNLOAD_DIR/${rec}.atr"
done

selected_records=$(wc -l < "$DOWNLOAD_DIR/RECORDS.selected" | tr -d ' ')
printf 'selected_records\n%s\n' "$selected_records" > "$FILTER_DIR/download_inventory.tsv"
echo "selected_records=$selected_records failure_count=$failure_count"
if [ "$failure_count" -ne 0 ]; then
  echo "[$(date -Is)] download failed dataset=$DATASET_ID"
  exit 1
fi
echo "[$(date -Is)] download done dataset=$DATASET_ID"
