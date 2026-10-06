#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="nasa_pds_magellan_fmidr_sar_u8"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
mkdir -p "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/verify.$RUN_TS.log" "$LOG_DIR/verify.latest.log") 2>&1
echo "[$(date -Is)] verify start dataset=$DATASET_ID"

python3 "$RECIPE_DIR/scripts/magellan_fmidr.py" selftest
python3 "$RECIPE_DIR/scripts/magellan_fmidr.py" verify \
  --sources "$RECIPE_DIR/sources.tsv" \
  --download-dir "$REPO_ROOT/$DATA_DIR/downloads/$DATASET_ID" \
  --data-root "$REPO_ROOT/$DATA_DIR" \
  --manifest "$RECIPE_DIR/manifest.toml" \
  --expected "$RECIPE_DIR/expected_output.json"

echo "[$(date -Is)] verify done dataset=$DATASET_ID"
