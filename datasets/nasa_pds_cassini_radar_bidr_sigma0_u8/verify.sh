#!/usr/bin/env bash
# Independently re-derive every sample from the local ZIPs (hand-parsed ZIP
# local header + raw zlib inflate + independent label regexes) and check the
# index, manifest totals, missing-value policy and non-degeneracy.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in /*) DATA_ROOT="$DATA_DIR" ;; *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;; esac
DATASET_ID="nasa_pds_cassini_radar_bidr_sigma0_u8"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"
mkdir -p "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/verify.$RUN_TS.log" "$LOG_DIR/verify.latest.log") 2>&1
echo "[$(date -Is)] verify start dataset=$DATASET_ID"

python3 "$RECIPE_DIR/scripts/verify.py" --recipe-dir "$RECIPE_DIR" --data-root "$DATA_ROOT"

echo "[$(date -Is)] verify done dataset=$DATASET_ID"
