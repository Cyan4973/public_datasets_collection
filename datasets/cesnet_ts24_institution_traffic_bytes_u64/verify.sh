#!/usr/bin/env bash
# Independently re-derive every institution series from the pinned archive and
# compare samples, index, manifest counts and pinned per-sample expectations.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATASET_ID="cesnet_ts24_institution_traffic_bytes_u64"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in
  /*) DATA_ROOT="$DATA_DIR" ;;
  *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;;
esac
DOWNLOAD_DIR="$DATA_ROOT/downloads/$DATASET_ID"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"
mkdir -p "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/verify.$RUN_TS.log" "$LOG_DIR/verify.latest.log") 2>&1
echo "[$(date -Is)] verify start dataset=$DATASET_ID"

python3 "$RECIPE_DIR/scripts/verify_samples.py" \
  --record "$DOWNLOAD_DIR/zenodo_record_13382427.json" \
  --times "$DOWNLOAD_DIR/times.tar.gz" \
  --archive "$DOWNLOAD_DIR/institutions.tar.gz" \
  --manifest "$RECIPE_DIR/manifest.toml" \
  --expected "$RECIPE_DIR/expected_samples.tsv" \
  --data-root "$DATA_ROOT"
echo "[$(date -Is)] verify done dataset=$DATASET_ID"
