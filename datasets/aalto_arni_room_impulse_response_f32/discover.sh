#!/usr/bin/env bash
# Metadata-only discovery: regenerate the pinned zip_archives.tsv and
# selection.tsv tables from the live Zenodo record.  Fetches the record JSON,
# a 64 KiB tail of each of the six ZIP archives and their exact central
# directories (~17.6 MB in total); no impulse-response member is downloaded.
# Not part of the acceptance path; download.sh re-derives and compares.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in /*) DATA_ROOT="$DATA_DIR" ;; *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;; esac
DATASET_ID="aalto_arni_room_impulse_response_f32"
OUT_DIR="$DATA_ROOT/discovery/$DATASET_ID"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"
TOOL="$RECIPE_DIR/scripts/arni_tool.py"
# shellcheck source=scripts/fetch_lib.sh
source "$RECIPE_DIR/scripts/fetch_lib.sh"

mkdir -p "$OUT_DIR" "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/discover.$RUN_TS.log" "$LOG_DIR/discover.latest.log") 2>&1
echo "[$(date -Is)] discover start dataset=$DATASET_ID"

arni_curl_get "$ARNI_API_URL" "$OUT_DIR/record.json" 20000000
python3 "$TOOL" archives-from-record --record "$OUT_DIR/record.json" > "$OUT_DIR/inventory.tsv"
cat "$OUT_DIR/inventory.tsv"

while IFS=$'\t' read -r archive size _md5; do
  arni_fetch_directory "$TOOL" "$OUT_DIR" "$archive" "$size"
done < "$OUT_DIR/inventory.tsv"

python3 "$TOOL" derive --meta-dir "$OUT_DIR" --inventory "$OUT_DIR/inventory.tsv" \
  --archives-out "$OUT_DIR/zip_archives.tsv" --selection-out "$OUT_DIR/selection.tsv"

for table in zip_archives.tsv selection.tsv; do
  if cmp -s "$OUT_DIR/$table" "$RECIPE_DIR/$table"; then
    echo "pinned $table matches live record"
  else
    echo "NOTE: $OUT_DIR/$table differs from pinned $RECIPE_DIR/$table"
  fi
done
echo "[$(date -Is)] discover done dataset=$DATASET_ID"
