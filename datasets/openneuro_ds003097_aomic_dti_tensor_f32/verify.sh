#!/usr/bin/env bash
# Independently re-decode every pinned source volume, require bit-exact
# samples, recompute statistics and the FA cross-check from the stored
# samples, and confirm the manifest's claimed scope.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in
  /*) DATA_ROOT="$DATA_DIR" ;;
  *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;;
esac
DATASET_ID="openneuro_ds003097_aomic_dti_tensor_f32"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"

mkdir -p "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/verify.$RUN_TS.log" "$LOG_DIR/verify.latest.log") 2>&1
echo "[$(date -Is)] verify start dataset=$DATASET_ID data_root=$DATA_ROOT"
python3 "$RECIPE_DIR/scripts/aomic_dti.py" verify \
  --selection "$RECIPE_DIR/selection.tsv" \
  --download-dir "$DATA_ROOT/downloads/$DATASET_ID" \
  --index "$DATA_ROOT/index/$DATASET_ID/samples.jsonl" \
  --data-root "$DATA_ROOT" \
  --manifest "$RECIPE_DIR/manifest.toml"
echo "[$(date -Is)] verify done dataset=$DATASET_ID"
