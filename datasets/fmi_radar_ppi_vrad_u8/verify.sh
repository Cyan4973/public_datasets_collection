#!/usr/bin/env bash
# Verify: local files only. Re-runs the decoder self-test, then re-derives every
# sample from its pinned source scan and re-checks the index, manifest totals,
# missing-value (NoData 255 / undetect 0) policy and non-degeneracy rules
# (scripts/fmivrad.py verify).
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in /*) DATA_ROOT="$DATA_DIR" ;; *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;; esac
DATASET_ID="fmi_radar_ppi_vrad_u8"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"

mkdir -p "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/verify.$RUN_TS.log" "$LOG_DIR/verify.latest.log") 2>&1
echo "[$(date -Is)] verify start dataset=$DATASET_ID data_root=$DATA_ROOT"

python3 "$RECIPE_DIR/scripts/fmivrad.py" selftest
python3 "$RECIPE_DIR/scripts/fmivrad.py" verify \
  --repo-root "$REPO_ROOT" --data-dir "$DATA_ROOT" --recipe-dir "$RECIPE_DIR"

echo "[$(date -Is)] verify done dataset=$DATASET_ID"
