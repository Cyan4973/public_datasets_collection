#!/usr/bin/env bash
# Build one N x 3 little-endian uint16 x,y,z sample per selected NCLT
# velodyne_sync revolution (every STRIDE-th in sorted utime order) by
# streaming the local tarball. Uses only files under ${DATA_DIR:-.data}.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in /*) DATA_ROOT="$DATA_DIR" ;; *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;; esac
DATASET_ID="umich_nclt_velodyne_hdl32e_xyz_u16"
SERIES_ID="nclt_velodyne_sync_xyz_u16"
STRIDE=5
MIN_HITS=1000
DOWNLOAD_DIR="$DATA_ROOT/downloads/$DATASET_ID"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"
ARCHIVE="$DOWNLOAD_DIR/2013-01-10_vel.tar.gz"
MEMBERS="$DOWNLOAD_DIR/members.tsv"
STATS="$DATA_ROOT/filtered/$DATASET_ID/build_stats.json"

mkdir -p "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/build.$RUN_TS.log" "$LOG_DIR/build.latest.log") 2>&1
echo "[$(date -Is)] build start dataset=$DATASET_ID"

for required in "$ARCHIVE" "$MEMBERS" "$DOWNLOAD_DIR/archive_receipt.json"; do
  if [ ! -s "$required" ]; then
    echo "FATAL: missing $required; run download.sh first" >&2
    exit 1
  fi
done

python3 "$RECIPE_DIR/scripts/build_samples.py" \
  --archive "$ARCHIVE" --members "$MEMBERS" --data-root "$DATA_ROOT" \
  --dataset-id "$DATASET_ID" --series-id "$SERIES_ID" \
  --stride "$STRIDE" --min-hits "$MIN_HITS" --stats "$STATS"

echo "[$(date -Is)] build done dataset=$DATASET_ID"
