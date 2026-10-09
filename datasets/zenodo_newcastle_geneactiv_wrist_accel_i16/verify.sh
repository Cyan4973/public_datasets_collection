#!/usr/bin/env bash
# Re-derive every sample from the local member spans with the independent
# per-word reference decoder and check bytes, index fields, the 12-bit range,
# non-degeneracy (constant, distinct-code, mode-share and static-page limits),
# acceptance floors, the 1 GB cap and the manifest totals.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in /*) DATA_ROOT="$DATA_DIR" ;; *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;; esac
DATASET_ID="zenodo_newcastle_geneactiv_wrist_accel_i16"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"
mkdir -p "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/verify.$RUN_TS.log" "$LOG_DIR/verify.latest.log") 2>&1
echo "[$(date -Is)] verify start dataset=$DATASET_ID data_root=$DATA_ROOT"

PY=(python3 -I "$RECIPE_DIR/scripts/geneactiv.py")
"${PY[@]}" check-cd "$DATA_ROOT/downloads/$DATASET_ID/zip_central_directory.bin" "$RECIPE_DIR/members.tsv"
"${PY[@]}" verify --data-root "$DATA_ROOT" --members "$RECIPE_DIR/members.tsv" --manifest "$RECIPE_DIR/manifest.toml"

echo "[$(date -Is)] verify done dataset=$DATASET_ID"
