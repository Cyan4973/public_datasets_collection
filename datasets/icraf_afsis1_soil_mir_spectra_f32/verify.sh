#!/usr/bin/env bash
# Independently re-derive every AfSIS1 MIR float32 sample from the local CSVs
# (csv module + decimal.Decimal lattice + array packing, a different parse
# path from build), and check bytes, lattice recoverability, index metadata,
# ingest statistics, degeneracy, and the manifest's claimed counts.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in /*) DATA_ROOT="$DATA_DIR" ;; *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;; esac
DATASET_ID="icraf_afsis1_soil_mir_spectra_f32"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"
mkdir -p "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/verify.$RUN_TS.log" "$LOG_DIR/verify.latest.log") 2>&1
echo "[$(date -Is)] verify start dataset=$DATASET_ID"

python3 "$RECIPE_DIR/scripts/afsis_mir.py" check-listing \
  --json "$DATA_ROOT/downloads/$DATASET_ID/dataset_version_1.1.json" \
  --sources "$RECIPE_DIR/sources.tsv"

python3 "$RECIPE_DIR/scripts/afsis_mir.py" verify \
  --sources "$RECIPE_DIR/sources.tsv" \
  --csv-dir "$DATA_ROOT/downloads/$DATASET_ID/csv" \
  --data-root "$DATA_ROOT" \
  --samples-dir "$DATA_ROOT/samples/$DATASET_ID" \
  --index "$DATA_ROOT/index/$DATASET_ID/samples.jsonl" \
  --stats "$DATA_ROOT/filtered/$DATASET_ID/ingest_stats.json" \
  --manifest "$RECIPE_DIR/manifest.toml"

echo "[$(date -Is)] verify done dataset=$DATASET_ID"
