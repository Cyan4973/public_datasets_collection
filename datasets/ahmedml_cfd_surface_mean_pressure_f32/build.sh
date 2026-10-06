#!/usr/bin/env bash
# Decode the locally downloaded pMean windows into one raw little-endian
# float32 sample per selected AhmedML run and write the sample index. Uses only
# files under ${DATA_DIR:-.data}.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in /*) DATA_ROOT="$DATA_DIR" ;; *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;; esac
DATASET_ID="ahmedml_cfd_surface_mean_pressure_f32"
DOWNLOAD_DIR="$DATA_ROOT/downloads/$DATASET_ID"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"
export PYTHONDONTWRITEBYTECODE=1
mkdir -p "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/build.$RUN_TS.log" "$LOG_DIR/build.latest.log") 2>&1
echo "[$(date -Is)] build start dataset=$DATASET_ID"

if [ ! -f "$DOWNLOAD_DIR/DOWNLOAD_OK" ]; then
  echo "FATAL: $DOWNLOAD_DIR/DOWNLOAD_OK missing; run download.sh first" >&2
  exit 1
fi
python3 "$RECIPE_DIR/scripts/ahmedml_vtp.py" selftest
python3 "$RECIPE_DIR/scripts/ahmedml_vtp.py" build \
  --selection "$RECIPE_DIR/selection.tsv" \
  --download-dir "$DOWNLOAD_DIR" \
  --data-root "$DATA_ROOT"

echo "[$(date -Is)] build done dataset=$DATASET_ID"
