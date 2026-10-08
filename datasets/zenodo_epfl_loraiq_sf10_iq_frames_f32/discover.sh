#!/usr/bin/env bash
# Documentation/reproduction of how selection.tsv was derived (not part of the
# acceptance path): range-fetch the ZIP64 tail and central directory of
# sigmfs.zip plus dataset.csv, then run scripts/discover.py.
set -euo pipefail

RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$RECIPE_DIR/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in /*) DATA_ROOT="$DATA_DIR" ;; *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;; esac
DATASET_ID="zenodo_epfl_loraiq_sf10_iq_frames_f32"
OUT="$DATA_ROOT/discovery/$DATASET_ID"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"
ARCHIVE_URL="https://zenodo.org/api/records/17708397/files/sigmfs.zip/content"
CSV_URL="https://zenodo.org/api/records/17708397/files/dataset.csv/content"
ARCHIVE_BYTES=49746561196
CD_OFFSET=49729255847
CD_SIZE=17305251
CD_SHA256="67649655a99f07102bb4adbb3294fe8c283a7a45812c253e8f84919ec0b634fa"
mkdir -p "$OUT" "$LOG_DIR"
exec > >(tee "$LOG_DIR/discover.latest.log") 2>&1
C=(curl --fail --silent --show-error --location --retry 5 --retry-delay 3 --retry-all-errors --max-time 900)
"${C[@]}" --range "$((ARCHIVE_BYTES - 65536))-$((ARCHIVE_BYTES - 1))" -o "$OUT/tail.bin" "$ARCHIVE_URL"
"${C[@]}" --range "$CD_OFFSET-$((CD_OFFSET + CD_SIZE - 1))" -o "$OUT/cd.bin" "$ARCHIVE_URL"
echo "$CD_SHA256  $OUT/cd.bin" | sha256sum --check
"${C[@]}" -o "$OUT/dataset.csv" "$CSV_URL"
python3 -I "$RECIPE_DIR/scripts/discover.py" --tail "$OUT/tail.bin" --cd "$OUT/cd.bin" \
  --csv "$OUT/dataset.csv" --out "$OUT/selection.tsv"
cmp "$OUT/selection.tsv" "$RECIPE_DIR/selection.tsv" && echo "selection.tsv reproduced exactly"
