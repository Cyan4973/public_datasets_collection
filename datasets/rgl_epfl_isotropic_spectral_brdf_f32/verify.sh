#!/usr/bin/env bash
# Independent re-derivation: re-parse each source file in memory, compare
# every sample byte-for-byte with its `spectra` field, recheck finiteness,
# zero/negative counts, stored-float32 min/max, degeneracy and totals.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="rgl_epfl_isotropic_spectral_brdf_f32"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
mkdir -p "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/verify.$RUN_TS.log" "$LOG_DIR/verify.latest.log") 2>&1
echo "[$(date -Is)] verify start dataset=$DATASET_ID"

python3 "$RECIPE_DIR/scripts/rgl_brdf.py" verify \
  --materials "$RECIPE_DIR/materials.tsv" \
  --manifest "$RECIPE_DIR/manifest.toml" \
  --downloads "$REPO_ROOT/$DATA_DIR/downloads/$DATASET_ID" \
  --samples-dir "$REPO_ROOT/$DATA_DIR/samples/$DATASET_ID" \
  --index "$REPO_ROOT/$DATA_DIR/index/$DATASET_ID/samples.jsonl" \
  --stats "$REPO_ROOT/$DATA_DIR/filtered/$DATASET_ID/ingest_stats.json" \
  --data-root "$REPO_ROOT/$DATA_DIR"

echo "[$(date -Is)] verify done dataset=$DATASET_ID"
