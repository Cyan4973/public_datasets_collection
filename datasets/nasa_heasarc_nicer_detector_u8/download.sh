#!/usr/bin/env bash
# Validate/reuse the pinned NICER source cache, fetching through its owner only if absent.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="nasa_heasarc_nicer_detector_u8"
SOURCE_DATASET_ID="nasa_heasarc_nicer_pi_i16"
RECIPE_DIR="$REPO_ROOT/datasets/$DATASET_ID"
SOURCE_RECIPE="$REPO_ROOT/datasets/$SOURCE_DATASET_ID"
DOWNLOAD_DIR="$REPO_ROOT/$DATA_DIR/downloads/$SOURCE_DATASET_ID"
DISCOVERY_DIR="$REPO_ROOT/$DATA_DIR/discovery/$DATASET_ID"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"

mkdir -p "$DISCOVERY_DIR" "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/download.$RUN_TS.log" "$LOG_DIR/download.latest.log") 2>&1
echo "[$(date -Is)] download start dataset=$DATASET_ID"

if [[ ! -f "$DOWNLOAD_DIR/download_inventory.json" ]]; then
  echo "shared NICER source cache absent; invoking pinned source-owner downloader"
  DATA_DIR="$DATA_DIR" bash "$SOURCE_RECIPE/download.sh"
else
  echo "reuse shared NICER source cache at $DOWNLOAD_DIR"
fi

python3 "$RECIPE_DIR/scripts/nicer_detector.py" preflight \
  --sources "$SOURCE_RECIPE/sources.tsv" --download-dir "$DOWNLOAD_DIR" \
  --profile "$DISCOVERY_DIR/source_profile.json"

echo "[$(date -Is)] download done dataset=$DATASET_ID"
