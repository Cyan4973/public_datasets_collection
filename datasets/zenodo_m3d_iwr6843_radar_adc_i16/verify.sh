#!/usr/bin/env bash
# Independently verify the M3D IWR6843AOP raw-ADC samples: re-inflate every
# pinned ZIP member range with a separate implementation, re-check config,
# DCA1000 log, size, CRC-32 and HSI headers, require each emitted sample to
# equal the re-derived header-stripped payload byte for byte, recompute
# min/max/SHA-256, reject constant or degenerate samples, and check the index
# and manifest totals.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in /*) DATA_ROOT="$DATA_DIR" ;; *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;; esac
DATASET_ID="zenodo_m3d_iwr6843_radar_adc_i16"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"
mkdir -p "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/verify.$RUN_TS.log" "$LOG_DIR/verify.latest.log") 2>&1
echo "[$(date -Is)] verify start dataset=$DATASET_ID"

python3 "$RECIPE_DIR/scripts/verify_samples.py" \
  --manifest "$RECIPE_DIR/manifest.toml" \
  --selection "$RECIPE_DIR/selection.tsv" \
  --download-dir "$DATA_ROOT/downloads/$DATASET_ID" \
  --data-root "$DATA_ROOT"

echo "[$(date -Is)] verify done dataset=$DATASET_ID"
