#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="tcia_lung_pet_ct_dx_u16"
DATA_ROOT="$REPO_ROOT/$DATA_DIR"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"

mkdir -p "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/verify.$RUN_TS.log" "$LOG_DIR/verify.latest.log") 2>&1
echo "[$(date -Is)] verify start dataset=$DATASET_ID"

python3 "$REPO_ROOT/datasets/$DATASET_ID/scripts/dicom_pet_volume.py" verify \
  --data-root "$DATA_ROOT" \
  --manifest "$REPO_ROOT/datasets/$DATASET_ID/manifest.toml"

echo "[$(date -Is)] verify done dataset=$DATASET_ID"
