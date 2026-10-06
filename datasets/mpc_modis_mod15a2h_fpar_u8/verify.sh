#!/usr/bin/env bash
# Independently verify mpc_modis_mod15a2h_fpar_u8 samples against local sources.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="mpc_modis_mod15a2h_fpar_u8"
case "$DATA_DIR" in /*) DATA_ROOT="$DATA_DIR" ;; *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;; esac
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"
DOWNLOAD_DIR="$DATA_ROOT/downloads/$DATASET_ID"
FILTER_DIR="$DATA_ROOT/filtered/$DATASET_ID"
INDEX_DIR="$DATA_ROOT/index/$DATASET_ID"
SAMPLES_DIR="$DATA_ROOT/samples/$DATASET_ID"
mkdir -p "$LOG_DIR"

RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/verify.$RUN_TS.log" "$LOG_DIR/verify.latest.log") 2>&1
echo "[$(date -Is)] verify start dataset=$DATASET_ID"

export REPO_ROOT RECIPE_DIR DATA_DIR DOWNLOAD_DIR FILTER_DIR INDEX_DIR SAMPLES_DIR
python3 "$RECIPE_DIR/scripts/verify_samples.py"

echo "[$(date -Is)] verify done dataset=$DATASET_ID"
