#!/usr/bin/env bash
# Download the pinned WIOD 2016-release World Input-Output Tables (Stata) archive
# from DataverseNL (doi:10.34894/PJ2M1C, dataset version 2.1, datafile 199103).
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in
  /*) DATA_ROOT="$DATA_DIR" ;;
  *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;;
esac
DATASET_ID="wiod2016_world_input_output_tables_f64"
DOWNLOAD_DIR="$DATA_ROOT/downloads/$DATASET_ID"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"
METADATA_URL="https://dataverse.nl/api/datasets/:persistentId/versions/2.1?persistentId=doi:10.34894/PJ2M1C"
ARCHIVE_URL="https://dataverse.nl/api/access/datafile/199103"
ARCHIVE_NAME="WIOTS_in_STATA.zip"
ARCHIVE_BYTES=638963496
MAX_ATTEMPTS="${MAX_ATTEMPTS:-30}"
UA="openzl-public-datasets-wiod2016/1.0"
PY="$RECIPE_DIR/scripts/wiod_wiot.py"

mkdir -p "$DOWNLOAD_DIR" "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/download.$RUN_TS.log" "$LOG_DIR/download.latest.log") 2>&1
echo "[$(date -Is)] download start dataset=$DATASET_ID"

# 1. Version-pinned dataset metadata: license terms and exact file identity.
metadata="$DOWNLOAD_DIR/dataset_v2.1.json"
rm -f "$metadata.part"
curl --globoff --fail --silent --show-error --location \
  --retry 5 --retry-delay 5 --retry-all-errors --max-time 120 --max-filesize 5000000 \
  --user-agent "$UA" --header "Accept: application/json" \
  --output "$metadata.part" "$METADATA_URL"
mv "$metadata.part" "$metadata"
python3 "$PY" validate-metadata --metadata "$metadata"

# 2. The archive. Every attempt re-requests the DataverseNL access URL, which
# answers 303 with a fresh signed objectstore.surf.nl URL (valid ~1 h), and
# resumes the .part file with a byte range. Stall detection, no hard timeout.
archive="$DOWNLOAD_DIR/$ARCHIVE_NAME"
part="$archive.part"
if [ "${FORCE_DOWNLOAD:-0}" = "1" ]; then
  rm -f "$archive" "$part"
fi
if [ -f "$archive" ]; then
  echo "cache_check path=$archive"
  python3 "$PY" validate-archive --archive "$archive"
else
  attempt=0
  while :; do
    have="$(stat -c %s "$part" 2>/dev/null || echo 0)"
    if [ "$have" -gt "$ARCHIVE_BYTES" ]; then
      echo "partial file larger than $ARCHIVE_BYTES bytes; discarding it"
      rm -f "$part"
      have=0
    fi
    if [ "$have" -eq "$ARCHIVE_BYTES" ]; then
      break
    fi
    attempt=$((attempt + 1))
    if [ "$attempt" -gt "$MAX_ATTEMPTS" ]; then
      echo "FATAL: archive incomplete after $MAX_ATTEMPTS attempts ($have of $ARCHIVE_BYTES bytes)" >&2
      exit 1
    fi
    echo "[$(date -Is)] fetch attempt=$attempt resume_from=$have of $ARCHIVE_BYTES"
    if curl --fail --silent --show-error --location --continue-at - \
      --retry 3 --retry-delay 10 --speed-limit 1024 --speed-time 120 \
      --user-agent "$UA" --output "$part" "$ARCHIVE_URL"; then
      :
    else
      rc=$?
      echo "curl exit=$rc; re-resolving the access URL in 15 s"
      sleep 15
    fi
  done
  echo "[$(date -Is)] transfer complete; validating size, SHA-1, ZIP members and Stata headers"
  if ! python3 "$PY" validate-archive --archive "$part"; then
    echo "FATAL: downloaded archive failed validation; removing the partial file" >&2
    rm -f "$part"
    exit 1
  fi
  mv "$part" "$archive"
fi

echo "[$(date -Is)] download done dataset=$DATASET_ID bytes=$(stat -c %s "$archive")"
