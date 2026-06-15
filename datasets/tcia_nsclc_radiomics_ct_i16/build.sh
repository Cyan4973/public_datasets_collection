#!/usr/bin/env bash
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="tcia_nsclc_radiomics_ct_i16"
SERIES_ID="ct_slice_pixels_i16"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
mkdir -p "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/build.$RUN_TS.log" "$LOG_DIR/build.latest.log") 2>&1
python3 "$REPO_ROOT/tools/numeric16_extract.py" build --repo-root "$REPO_ROOT" --data-dir "$DATA_DIR" --dataset-id "$DATASET_ID" --series-id "$SERIES_ID" --format dicom
