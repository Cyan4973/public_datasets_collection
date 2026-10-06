#!/usr/bin/env bash
# Independently re-derive the selection from the cached SOP listings, re-parse
# every source DICOM-CT-PD object, cross-check the trailing Pixel Data element,
# byte-compare every sample, recompute every index row and statistic, reject
# constant or low-cardinality views, and check the manifest claims.
set -euo pipefail

RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$RECIPE_DIR/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in
  /*) DATA_ROOT="$DATA_DIR" ;;
  *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;;
esac
DATASET_ID="tcia_ldct_siemens_ct_projections_u16"
SERIES_ID="siemens_full_dose_projection_view_u16"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"
export PYTHONDONTWRITEBYTECODE=1

mkdir -p "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/verify.$RUN_TS.log" "$LOG_DIR/verify.latest.log") 2>&1
echo "[$(date -Is)] verify start dataset=$DATASET_ID data_root=$DATA_ROOT"

python3 "$RECIPE_DIR/scripts/ldct_ctpd.py" selftest
python3 "$RECIPE_DIR/scripts/ldct_ctpd.py" verify \
  --download-dir "$DATA_ROOT/downloads/$DATASET_ID" \
  --pins "$RECIPE_DIR/series_pins.tsv" \
  --data-root "$DATA_ROOT" \
  --samples-dir "$DATA_ROOT/samples/$DATASET_ID/$SERIES_ID" \
  --index "$DATA_ROOT/index/$DATASET_ID/samples.jsonl" \
  --stats "$DATA_ROOT/filtered/$DATASET_ID/ingest_stats.json" \
  --manifest "$RECIPE_DIR/manifest.toml"

echo "[$(date -Is)] verify done dataset=$DATASET_ID"
