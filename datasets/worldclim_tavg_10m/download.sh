#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="worldclim_tavg_10m"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
DOWNLOAD_DIR="$REPO_ROOT/$DATA_DIR/downloads/$DATASET_ID"
EXTRACT_DIR="$REPO_ROOT/$DATA_DIR/extracted/$DATASET_ID"
FILTER_DIR="$REPO_ROOT/$DATA_DIR/filtered/$DATASET_ID"
INDEX_DIR="$REPO_ROOT/$DATA_DIR/index/$DATASET_ID"
SAMPLES_DIR="$REPO_ROOT/$DATA_DIR/samples/$DATASET_ID"
mkdir -p "$LOG_DIR" "$DOWNLOAD_DIR" "$EXTRACT_DIR" "$FILTER_DIR" "$INDEX_DIR" "$SAMPLES_DIR"

RUN_TS="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="$LOG_DIR/download.$RUN_TS.log"
LATEST_LOG="$LOG_DIR/download.latest.log"
FAILURES_FILE="$DOWNLOAD_DIR/download_failures.tsv"
exec > >(tee "$LOG_FILE" "$LATEST_LOG") 2>&1

ARCHIVE_NAME="wc2.1_10m_tavg.zip"
ARCHIVE_PATH="$DOWNLOAD_DIR/$ARCHIVE_NAME"
SOURCE_URL="https://geodata.ucdavis.edu/climate/worldclim/2_1/base/$ARCHIVE_NAME"
EXPECTED_BYTES="37364656"
EXPECTED_SHA256="5e567dcfe94379b94229492849ce91078b1c6e5210aaf435fba449fae6b95405"

echo "[$(date -Is)] download start dataset=$DATASET_ID"
printf 'resource\tstatus\tdetail\n' > "$FAILURES_FILE"

validate_archive() {
  local path="$1"
  local actual_bytes actual_sha256
  actual_bytes="$(wc -c < "$path" | tr -d ' ')"
  if [[ "$actual_bytes" != "$EXPECTED_BYTES" ]]; then
    echo "size mismatch path=$path actual=$actual_bytes expected=$EXPECTED_BYTES"
    return 1
  fi
  actual_sha256="$(sha256sum "$path" | awk '{print $1}')"
  if [[ "$actual_sha256" != "$EXPECTED_SHA256" ]]; then
    echo "sha256 mismatch path=$path actual=$actual_sha256 expected=$EXPECTED_SHA256"
    return 1
  fi
}

if [[ -n "${WORLDCLIM_ARCHIVE:-}" ]]; then
  echo "using local archive WORLDCLIM_ARCHIVE=$WORLDCLIM_ARCHIVE"
  cp "$WORLDCLIM_ARCHIVE" "$ARCHIVE_PATH.tmp"
  mv "$ARCHIVE_PATH.tmp" "$ARCHIVE_PATH"
else
  if [[ -f "$ARCHIVE_PATH" ]]; then
    echo "found cached archive $ARCHIVE_PATH"
    if ! validate_archive "$ARCHIVE_PATH"; then
      echo "cached archive invalid; removing"
      rm -f "$ARCHIVE_PATH"
    fi
  fi
  if [[ ! -f "$ARCHIVE_PATH" ]]; then
    echo "downloading url=$SOURCE_URL"
    if command -v curl >/dev/null 2>&1; then
      curl -L --fail --show-error --retry 3 --retry-delay 5 --output "$ARCHIVE_PATH.tmp" "$SOURCE_URL"
    elif command -v wget >/dev/null 2>&1; then
      wget -O "$ARCHIVE_PATH.tmp" "$SOURCE_URL"
    else
      echo -e "main_archive\tfailed\tneed curl or wget" >> "$FAILURES_FILE"
      echo "missing curl/wget"
      exit 1
    fi
    mv "$ARCHIVE_PATH.tmp" "$ARCHIVE_PATH"
  fi
fi

if validate_archive "$ARCHIVE_PATH"; then
  echo "archive validated path=$ARCHIVE_PATH"
else
  echo -e "main_archive\tfailed\tarchive failed size or sha256 validation" >> "$FAILURES_FILE"
  exit 1
fi

grep -q $'\tfailed\t' "$FAILURES_FILE" && failure_count=1 || failure_count=0
echo "failure_count=$failure_count"
echo "[$(date -Is)] download done dataset=$DATASET_ID"
exit "$failure_count"
