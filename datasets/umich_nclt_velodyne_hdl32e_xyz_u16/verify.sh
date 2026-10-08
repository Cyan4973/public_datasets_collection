#!/usr/bin/env bash
# Independently re-derive and check every NCLT velodyne_sync x,y,z uint16
# sample from the local tarball (see scripts/verify_samples.py).
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in /*) DATA_ROOT="$DATA_DIR" ;; *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;; esac
DATASET_ID="umich_nclt_velodyne_hdl32e_xyz_u16"
SERIES_ID="nclt_velodyne_sync_xyz_u16"
STRIDE=5
MIN_HITS=1000
ARCHIVE_SHA256="92118ba5dc8e197eb0dfd817a006b1acc20ff1efb2fa53be02f61d40d6438ccb"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"
ARCHIVE="$DATA_ROOT/downloads/$DATASET_ID/2013-01-10_vel.tar.gz"
STATS="$DATA_ROOT/filtered/$DATASET_ID/build_stats.json"

mkdir -p "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/verify.$RUN_TS.log" "$LOG_DIR/verify.latest.log") 2>&1
echo "[$(date -Is)] verify start dataset=$DATASET_ID"

python3 "$RECIPE_DIR/scripts/verify_samples.py" \
  --archive "$ARCHIVE" --archive-sha256 "$ARCHIVE_SHA256" --data-root "$DATA_ROOT" \
  --dataset-id "$DATASET_ID" --series-id "$SERIES_ID" \
  --stride "$STRIDE" --min-hits "$MIN_HITS" --stats "$STATS" \
  --manifest "$RECIPE_DIR/manifest.toml"

echo "[$(date -Is)] verify done dataset=$DATASET_ID"
