#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="uci_hydraulic_system_cycles_f32"
RECIPE_DIR="$REPO_ROOT/staging/$DATASET_ID"
DOWNLOAD_DIR="$REPO_ROOT/$DATA_DIR/downloads/$DATASET_ID"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
mkdir -p "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/verify.$RUN_TS.log" "$LOG_DIR/verify.latest.log") 2>&1
echo "[$(date -Is)] verify start dataset=$DATASET_ID"
python3 "$RECIPE_DIR/scripts/hydraulic.py" verify \
  --archive "$DOWNLOAD_DIR/hydraulic_systems.zip" \
  --metadata "$DOWNLOAD_DIR/uci_dataset_447.json" \
  --rights "$DOWNLOAD_DIR/uci_dataset_447.html" \
  --index "$REPO_ROOT/$DATA_DIR/index/$DATASET_ID/samples.jsonl" \
  --stats "$REPO_ROOT/$DATA_DIR/filtered/$DATASET_ID/ingest_stats.json" \
  --data-root "$REPO_ROOT/$DATA_DIR"
echo "[$(date -Is)] verify done dataset=$DATASET_ID"
