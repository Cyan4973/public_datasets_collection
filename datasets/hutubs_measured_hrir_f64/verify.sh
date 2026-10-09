#!/usr/bin/env bash
# Independently re-derive every sample from the local SOFA files (separate
# inflate + unshuffle path) and check the index, missing-value policy,
# degeneracy rules and manifest totals.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in /*) DATA_ROOT="$DATA_DIR" ;; *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;; esac
DATASET_ID="hutubs_measured_hrir_f64"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"
mkdir -p "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/verify.$RUN_TS.log" "$LOG_DIR/verify.latest.log") 2>&1
echo "[$(date -Is)] verify start dataset=$DATASET_ID"

python3 -I "$RECIPE_DIR/scripts/selftest.py"
python3 -I "$RECIPE_DIR/scripts/hutubs_sofa.py" verify \
  --downloads "$DATA_ROOT/downloads/$DATASET_ID" \
  --files-tsv "$RECIPE_DIR/files.tsv" \
  --data-root "$DATA_ROOT" \
  --manifest "$RECIPE_DIR/manifest.toml"

echo "[$(date -Is)] verify done dataset=$DATASET_ID"
