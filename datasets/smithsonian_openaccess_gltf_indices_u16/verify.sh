#!/usr/bin/env bash
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="smithsonian_openaccess_gltf_indices_u16"
SERIES_ID="mesh_index_accessors_u16"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
mkdir -p "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/verify.$RUN_TS.log" "$LOG_DIR/verify.latest.log") 2>&1
python3 "$REPO_ROOT/tools/numeric16_extract.py" verify --repo-root "$REPO_ROOT" --data-dir "$DATA_DIR" --dataset-id "$DATASET_ID" --series-id "$SERIES_ID" --format gltf
