#!/usr/bin/env bash
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="bbbc039_microscopy_tiff_u16"
SERIES_ID="bbbc039_microscopy_u16"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
mkdir -p "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/build.$RUN_TS.log" "$LOG_DIR/build.latest.log") 2>&1
python3 "$REPO_ROOT/tools/numeric16_extract.py" build --repo-root "$REPO_ROOT" --data-dir "$DATA_DIR" --dataset-id "$DATASET_ID" --series-id "$SERIES_ID" --format tiff
