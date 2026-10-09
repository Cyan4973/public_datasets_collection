#!/usr/bin/env bash
# Independently re-derive every MIMIC-III ABP sample from the downloads and
# check bytes, index rows, ingest stats, keep policy and manifest totals.
set -euo pipefail
export PYTHONDONTWRITEBYTECODE=1  # keep the recipe directory free of __pycache__

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in
  /*) DATA_ROOT="$DATA_DIR" ;;
  *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;;
esac
DATASET_ID="physionet_mimic3wdb_abp_i8"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"

mkdir -p "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/verify.$RUN_TS.log" "$LOG_DIR/verify.latest.log") 2>&1
echo "[$(date -Is)] verify start dataset=$DATASET_ID data_root=$DATA_ROOT"

python3 "$RECIPE_DIR/scripts/mimic_verify.py" \
  --download-dir "$DATA_ROOT/downloads/$DATASET_ID" \
  --samples-root "$DATA_ROOT/samples/$DATASET_ID" \
  --index "$DATA_ROOT/index/$DATASET_ID/samples.jsonl" \
  --stats "$DATA_ROOT/filtered/$DATASET_ID/ingest_stats.json" \
  --data-root "$DATA_ROOT" \
  --manifest "$RECIPE_DIR/manifest.toml"

echo "[$(date -Is)] verify done dataset=$DATASET_ID"
