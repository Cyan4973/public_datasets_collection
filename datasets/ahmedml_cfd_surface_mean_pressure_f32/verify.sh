#!/usr/bin/env bash
# Independently re-derive every AhmedML pMean sample from the local windows
# with an offset-free decoder (tag search + whitespace strip), byte-compare it
# with the emitted sample and the offset-based decoder, recompute index fields
# (min/max from the stored float32 values, sha256), and reject non-finite,
# constant, low-diversity or duplicate fields and manifest/realized mismatches.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in /*) DATA_ROOT="$DATA_DIR" ;; *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;; esac
DATASET_ID="ahmedml_cfd_surface_mean_pressure_f32"
DOWNLOAD_DIR="$DATA_ROOT/downloads/$DATASET_ID"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"
export PYTHONDONTWRITEBYTECODE=1
mkdir -p "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/verify.$RUN_TS.log" "$LOG_DIR/verify.latest.log") 2>&1
echo "[$(date -Is)] verify start dataset=$DATASET_ID"

python3 "$RECIPE_DIR/scripts/ahmedml_vtp.py" selftest
python3 "$RECIPE_DIR/scripts/ahmedml_vtp.py" verify \
  --selection "$RECIPE_DIR/selection.tsv" \
  --download-dir "$DOWNLOAD_DIR" \
  --data-root "$DATA_ROOT" \
  --manifest "$RECIPE_DIR/manifest.toml"

echo "[$(date -Is)] verify done dataset=$DATASET_ID"
