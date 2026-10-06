#!/usr/bin/env bash
# Build one raw little-endian float32 sample per selected Arni impulse
# response from the locally downloaded WAV members (local files only).
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in /*) DATA_ROOT="$DATA_DIR" ;; *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;; esac
DATASET_ID="aalto_arni_room_impulse_response_f32"
DOWNLOAD_DIR="$DATA_ROOT/downloads/$DATASET_ID"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"

mkdir -p "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/build.$RUN_TS.log" "$LOG_DIR/build.latest.log") 2>&1
echo "[$(date -Is)] build start dataset=$DATASET_ID"

if [ ! -d "$DOWNLOAD_DIR/wav" ] || [ ! -s "$DOWNLOAD_DIR/combinations_setup.csv" ]; then
  echo "FATAL: missing downloads under $DOWNLOAD_DIR; run download.sh first" >&2
  exit 1
fi

python3 "$RECIPE_DIR/scripts/build_samples.py" \
  --selection "$RECIPE_DIR/selection.tsv" \
  --wav-dir "$DOWNLOAD_DIR/wav" \
  --csv "$DOWNLOAD_DIR/combinations_setup.csv" \
  --data-root "$DATA_ROOT"

echo "[$(date -Is)] build done dataset=$DATASET_ID"
