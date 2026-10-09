#!/usr/bin/env bash
# Independently re-derive every sample from the downloaded FITS products and
# check the samples, the index, the quality policy and the manifest totals.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
[[ "$DATA_DIR" = /* ]] || DATA_DIR="$REPO_ROOT/$DATA_DIR"
CANDIDATE_ID="nasa_pds_m2020_supercam_libs_mic_audio_i16"
LOG_DIR="$DATA_DIR/logs/$CANDIDATE_ID"

mkdir -p "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/verify.$RUN_TS.log" "$LOG_DIR/verify.latest.log") 2>&1
echo "[$(date -Is)] verify start candidate=$CANDIDATE_ID"

python3 "$RECIPE_DIR/scripts/verify_mic.py" \
  --recipe-dir "$RECIPE_DIR" \
  --data-root "$DATA_DIR"

echo "[$(date -Is)] verify done candidate=$CANDIDATE_ID"
