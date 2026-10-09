#!/usr/bin/env bash
# Decode the 30 local E4 ACC.csv session files into one interleaved x,y,z
# int8 sample per exam session, plus the sample index and ingest stats.
set -euo pipefail
export PYTHONDONTWRITEBYTECODE=1  # keep the recipe directory free of __pycache__

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in
  /*) DATA_ROOT="$DATA_DIR" ;;
  *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;;
esac
DATASET_ID="physionet_wearable_exam_stress_e4_acc_i8"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"

mkdir -p "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/build.$RUN_TS.log" "$LOG_DIR/build.latest.log") 2>&1
echo "[$(date -Is)] build start dataset=$DATASET_ID data_root=$DATA_ROOT"

[[ -f "$DATA_ROOT/downloads/$DATASET_ID/download_inventory.json" ]] || {
  echo "missing download inventory; run download.sh first" >&2
  exit 1
}

python3 "$RECIPE_DIR/scripts/e4acc_build.py" \
  --download-dir "$DATA_ROOT/downloads/$DATASET_ID" \
  --samples-root "$DATA_ROOT/samples/$DATASET_ID" \
  --index "$DATA_ROOT/index/$DATASET_ID/samples.jsonl" \
  --stats "$DATA_ROOT/filtered/$DATASET_ID/ingest_stats.json" \
  --data-root "$DATA_ROOT"

echo "[$(date -Is)] build done dataset=$DATASET_ID"
