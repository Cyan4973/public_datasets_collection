#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$REPO_ROOT/datasets/zenodo_venere_nir_hsi_u16"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="zenodo_venere_nir_hsi_u16"
DOWNLOAD_DIR="$REPO_ROOT/$DATA_DIR/downloads/$DATASET_ID"
FILTERED_DIR="$REPO_ROOT/$DATA_DIR/filtered/$DATASET_ID"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
mkdir -p "$FILTERED_DIR" "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/inspect.$RUN_TS.log" "$LOG_DIR/inspect.latest.log") 2>&1
echo "[$(date -Is)] inspect start dataset=$DATASET_ID"
python3 "$RECIPE_DIR/scripts/inspect_envi_u16.py" \
  --header "$DOWNLOAD_DIR/venere.hdr" \
  --payload "$DOWNLOAD_DIR/venere.raw" \
  --report "$FILTERED_DIR/preflight.json"
echo "[$(date -Is)] inspect done dataset=$DATASET_ID"
