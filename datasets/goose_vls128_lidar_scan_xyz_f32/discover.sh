#!/usr/bin/env bash
# Documents how sources.tsv was resolved. Not part of the acceptance path.
#
# Fetches only the goose_3d_val.zip tail (316,905 bytes: LICENSE, CHANGELOG and
# label-mapping members, the 1,925-entry central directory, ZIP64 end records
# and EOCD), re-derives the selection (8 sweeps per val sequence, centred in
# equal frame-order strata) and diffs it against the pinned sources.tsv.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in /*) DATA_ROOT="$DATA_DIR" ;; *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;; esac
DATASET_ID="goose_vls128_lidar_scan_xyz_f32"
OUT_DIR="$DATA_ROOT/discovery/$DATASET_ID"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"
mkdir -p "$OUT_DIR" "$LOG_DIR"
exec > >(tee "$LOG_DIR/discover.latest.log") 2>&1

curl --fail --silent --show-error --location --retry 5 --max-time 300 \
  --range 3498085530-3498402434 --dump-header "$OUT_DIR/archive_tail.headers" \
  --output "$OUT_DIR/archive_tail.bin" "https://goose-dataset.de/storage/goose_3d_val.zip"
python3 "$RECIPE_DIR/scripts/goose_zip.py" select --tail "$OUT_DIR/archive_tail.bin" \
  --out "$OUT_DIR/sources.tsv"
diff -u "$RECIPE_DIR/sources.tsv" "$OUT_DIR/sources.tsv" && echo "selection matches pinned sources.tsv"
