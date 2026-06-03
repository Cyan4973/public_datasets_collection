#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="citibike_2024_01_station_ids_u16"
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

ARCHIVE_NAME="202401-citibike-tripdata.zip"
ARCHIVE_PATH="$DOWNLOAD_DIR/$ARCHIVE_NAME"
SOURCE_URL="https://s3.amazonaws.com/tripdata/$ARCHIVE_NAME"
EXPECTED_BYTES="369035302"
EXPECTED_SHA256="0a2e81eacd7bf3890712de8f2a1b56bda985c17d9e61b08acf5e7c7ec9f20eb0"
USER_AGENT="openzl-transformer-public-datasets/1.0"

echo "[$(date -Is)] download start dataset=$DATASET_ID"
printf 'resource\tstatus\tdetail\n' > "$FAILURES_FILE"

validate_archive() {
  local path="$1" actual_bytes actual_sha256
  actual_bytes="$(wc -c < "$path" | tr -d ' ')"
  [[ "$actual_bytes" == "$EXPECTED_BYTES" ]] || { echo "size mismatch actual=$actual_bytes expected=$EXPECTED_BYTES"; return 1; }
  actual_sha256="$(sha256sum "$path" | awk '{print $1}')"
  [[ "$actual_sha256" == "$EXPECTED_SHA256" ]] || { echo "sha256 mismatch actual=$actual_sha256 expected=$EXPECTED_SHA256"; return 1; }
}

if [[ -n "${CITIBIKE_ARCHIVE:-}" ]]; then
  echo "using local archive CITIBIKE_ARCHIVE=$CITIBIKE_ARCHIVE"
  cp "$CITIBIKE_ARCHIVE" "$ARCHIVE_PATH.tmp"
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
      curl -L --fail --show-error --retry 3 --retry-delay 5 -A "$USER_AGENT" --output "$ARCHIVE_PATH.tmp" "$SOURCE_URL"
    elif command -v wget >/dev/null 2>&1; then
      wget -U "$USER_AGENT" -O "$ARCHIVE_PATH.tmp" "$SOURCE_URL"
    else
      echo -e "january_2024_zip\tfailed\tneed curl or wget" >> "$FAILURES_FILE"
      exit 1
    fi
    mv "$ARCHIVE_PATH.tmp" "$ARCHIVE_PATH"
  fi
fi

if validate_archive "$ARCHIVE_PATH"; then
  echo "archive validated path=$ARCHIVE_PATH"
else
  echo -e "january_2024_zip\tfailed\tarchive failed size or sha256 validation" >> "$FAILURES_FILE"
  exit 1
fi

if grep -q $'\tfailed\t' "$FAILURES_FILE"; then
  failure_count="$(grep -c $'\tfailed\t' "$FAILURES_FILE")"
else
  failure_count=0
fi
echo "failure_count=$failure_count"
echo "[$(date -Is)] download done dataset=$DATASET_ID"
exit "$failure_count"
