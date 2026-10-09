#!/usr/bin/env bash
# Independently re-decode every source TIFF with a separately written decoder,
# byte-compare with the samples, and check index, totals and degeneracy.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in /*) DATA_ROOT="$DATA_DIR" ;; *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;; esac
DATASET_ID="zenodo_offaxis_dhm_holograms_u8"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"
mkdir -p "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/verify.$RUN_TS.log" "$LOG_DIR/verify.latest.log") 2>&1
echo "[$(date -Is)] verify start dataset=$DATASET_ID"

python3 -I "$RECIPE_DIR/scripts/dhm_verify.py" --recipe "$RECIPE_DIR" --data-root "$DATA_ROOT" \
  --full-decode-every "${VERIFY_DECODE_EVERY:-1}"

echo "[$(date -Is)] verify done dataset=$DATASET_ID"
