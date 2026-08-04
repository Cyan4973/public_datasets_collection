#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
CANDIDATE_ID="tcia_lung_pet_ct_dx_u16"
DOWNLOAD_DIR="$REPO_ROOT/$DATA_DIR/downloads/$CANDIDATE_ID"
OUT_DIR="$REPO_ROOT/$DATA_DIR/discovery/$CANDIDATE_ID"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$CANDIDATE_ID"

mkdir -p "$OUT_DIR" "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/inspect_probe.$RUN_TS.log" "$LOG_DIR/inspect_probe.latest.log") 2>&1
echo "[$(date -Is)] PET DICOM inspection start dataset=$CANDIDATE_ID"

python3 "$REPO_ROOT/datasets/$CANDIDATE_ID/scripts/dicom_pet_volume.py" inspect \
  --download-dir "$DOWNLOAD_DIR" \
  --output-dir "$OUT_DIR"

echo "[$(date -Is)] PET DICOM inspection done dataset=$CANDIDATE_ID"
