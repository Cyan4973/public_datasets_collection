#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="tum_rgbd_groundtruth_pose_f64"
NAME="rgbd_dataset_freiburg1_xyz.tgz"
SOURCE_URL="https://cvg.cit.tum.de/rgbd/dataset/freiburg1/$NAME"
EXPECTED_SIZE=448204271
EXPECTED_SHA256="a0236d97b8c30cd93b653656d2b6c293ff7c982a4130ef2a1a8beecdb124ef98"
DOWNLOAD_DIR="$REPO_ROOT/$DATA_DIR/downloads/$DATASET_ID"
REUSE_FILE="$REPO_ROOT/$DATA_DIR/downloads/tum_rgbd_depth_u16/$NAME"
TARGET="$DOWNLOAD_DIR/$NAME"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"

mkdir -p "$DOWNLOAD_DIR" "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/download.$RUN_TS.log" "$LOG_DIR/download.latest.log") 2>&1
echo "[$(date -Is)] download start dataset=$DATASET_ID"

check_file() {
  local path="$1"
  [[ -f "$path" ]] || return 1
  [[ "$(wc -c < "$path" | tr -d ' ')" == "$EXPECTED_SIZE" ]] || return 1
  [[ "$(sha256sum "$path" | awk '{print $1}')" == "$EXPECTED_SHA256" ]]
}

if check_file "$TARGET"; then
  echo "validated existing $TARGET"
else
  rm -f "$TARGET" "$TARGET.part"
  if check_file "$REUSE_FILE"; then
    echo "reuse validated accepted-cache source $REUSE_FILE"
    ln "$REUSE_FILE" "$TARGET" 2>/dev/null || cp --reflink=auto "$REUSE_FILE" "$TARGET"
  else
    curl --fail --location --retry 5 --retry-delay 3 \
      --user-agent "openzl-public-datasets/1.0" \
      --max-filesize 500000000 --output "$TARGET.part" "$SOURCE_URL"
    mv "$TARGET.part" "$TARGET"
  fi
  check_file "$TARGET" || { echo "source size or SHA-256 mismatch" >&2; exit 1; }
fi

python3 "$REPO_ROOT/datasets/$DATASET_ID/scripts/tum_pose.py" inspect "$TARGET"
printf 'source_url\tlocal_name\tbytes\tsha256\n%s\t%s\t%s\t%s\n' \
  "$SOURCE_URL" "$NAME" "$EXPECTED_SIZE" "$EXPECTED_SHA256" \
  > "$DOWNLOAD_DIR/download_inventory.tsv"
echo "[$(date -Is)] download done dataset=$DATASET_ID"
