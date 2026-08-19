#!/usr/bin/env bash
# Download and preflight the exact CC BY 4.0 Urban DAS archive.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$REPO_ROOT/datasets/zenodo_spica_urban_das_f32"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="zenodo_spica_urban_das_f32"
DOWNLOAD_DIR="$REPO_ROOT/$DATA_DIR/downloads/$DATASET_ID"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
TARGET="$DOWNLOAD_DIR/JGR_2019-master.zip"
EXPECTED_SIZE=92177152
EXPECTED_MD5="bd3cf8f38eeed0aadd3ebfdd1344f87d"
URL="https://zenodo.org/api/records/3549085/files/JGR_2019-master.zip/content"

mkdir -p "$DOWNLOAD_DIR" "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/download.$RUN_TS.log" "$LOG_DIR/download.latest.log") 2>&1
echo "[$(date -Is)] download start dataset=$DATASET_ID"

if [[ -f "$TARGET" ]] \
  && [[ "$(stat -c %s "$TARGET")" == "$EXPECTED_SIZE" ]] \
  && [[ "$(md5sum "$TARGET" | awk '{print $1}')" == "$EXPECTED_MD5" ]]; then
  echo "verified cached $(basename "$TARGET")"
else
  PART="$TARGET.part"
  rm -f "$PART"
  echo "downloading $(basename "$TARGET") bytes=$EXPECTED_SIZE"
  curl --fail --location --retry 5 --retry-delay 2 --max-time 3600 \
    --output "$PART" "$URL"
  ACTUAL_SIZE="$(stat -c %s "$PART")"
  ACTUAL_MD5="$(md5sum "$PART" | awk '{print $1}')"
  [[ "$ACTUAL_SIZE" == "$EXPECTED_SIZE" ]] || { echo "size mismatch: $ACTUAL_SIZE != $EXPECTED_SIZE" >&2; exit 1; }
  [[ "$ACTUAL_MD5" == "$EXPECTED_MD5" ]] || { echo "MD5 mismatch: $ACTUAL_MD5 != $EXPECTED_MD5" >&2; exit 1; }
  mv "$PART" "$TARGET"
fi

python3 "$RECIPE_DIR/scripts/miniseed_f32.py" inspect --archive "$TARGET"
echo "[$(date -Is)] download done dataset=$DATASET_ID"
