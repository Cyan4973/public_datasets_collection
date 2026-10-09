#!/usr/bin/env bash
# Documentation-only: regenerate the pinned day list (days.tsv) from the live
# S3 listing plus ~80 KB of HDF5 header/tail range reads per probed day.
# Not part of download/build. Writes to $DATA_DIR/discovery/<id>/days.tsv;
# compare against the committed days.tsv before replacing it.
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in /*) ;; *) DATA_DIR="$REPO_ROOT/$DATA_DIR" ;; esac
DATASET_ID="mbari_mars_hydrophone_hmd_psd_f32"
OUT_DIR="$DATA_DIR/discovery/$DATASET_ID"
LOG_DIR="$DATA_DIR/logs/$DATASET_ID"
mkdir -p "$OUT_DIR" "$LOG_DIR"
python3 -I "$RECIPE_DIR/scripts/discover.py" --count 36 --out "$OUT_DIR/days.tsv" \
  2> >(tee "$LOG_DIR/discover.latest.log" >&2)
diff -u "$RECIPE_DIR/days.tsv" "$OUT_DIR/days.tsv" && echo "days.tsv unchanged"
