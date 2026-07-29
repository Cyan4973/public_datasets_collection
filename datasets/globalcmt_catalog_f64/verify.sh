#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="globalcmt_catalog_f64"
SOURCE_FILE="$REPO_ROOT/$DATA_DIR/downloads/$DATASET_ID/jan76_dec20.ndk"
INDEX_FILE="$REPO_ROOT/$DATA_DIR/index/$DATASET_ID/samples.jsonl"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"

mkdir -p "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/verify.$RUN_TS.log" "$LOG_DIR/verify.latest.log") 2>&1

echo "[$(date -Is)] verify start dataset=$DATASET_ID"
python3 "$REPO_ROOT/datasets/$DATASET_ID/scripts/globalcmt_ndk.py" verify \
  --source "$SOURCE_FILE" \
  --index "$INDEX_FILE" \
  --data-root "$REPO_ROOT/$DATA_DIR"
echo "[$(date -Is)] verify done dataset=$DATASET_ID"
