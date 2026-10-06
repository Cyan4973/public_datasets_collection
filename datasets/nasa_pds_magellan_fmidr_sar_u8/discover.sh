#!/usr/bin/env bash
# Metadata-only discovery: S3 listings plus 1 KiB per-MIDR HIST.TAB files.
# Regenerates the pinned source plan and checks it against sources.tsv.
# SURVEY=1 fetches HIST.TAB for every F-MIDR directory (~765 KiB) to rank
# all candidates; the default fetches only the six selected MIDRs.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="nasa_pds_magellan_fmidr_sar_u8"
BASE="https://asc-pds-magellan.s3.us-west-2.amazonaws.com"
OUT="$REPO_ROOT/$DATA_DIR/discovery/$DATASET_ID"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
HELPER="$RECIPE_DIR/scripts/discover.py"

mkdir -p "$OUT/volumes" "$OUT/hist" "$OUT/selected" "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/discover.$RUN_TS.log" "$LOG_DIR/discover.latest.log") 2>&1
echo "[$(date -Is)] discovery start dataset=$DATASET_ID"

fetch() {
  curl --fail --silent --show-error --location --retry 5 --retry-delay 2 \
    --max-time 120 --output "$2" "$1"
}

fetch "$BASE/?list-type=2&delimiter=/" "$OUT/root.xml"
for volume in $(python3 "$HELPER" volumes --root "$OUT/root.xml"); do
  fetch "$BASE/?list-type=2&prefix=$volume/&delimiter=/" "$OUT/volumes/$volume.xml"
done
python3 "$HELPER" fmidr-dirs --volumes-dir "$OUT/volumes" > "$OUT/fmidr_dirs.txt"

if [[ "${SURVEY:-0}" == "1" ]]; then
  hist_dirs="$(cat "$OUT/fmidr_dirs.txt")"
else
  hist_dirs="$(python3 "$HELPER" selected)"
fi
for dir in $hist_dirs; do
  target="$OUT/hist/${dir/\//_}.tab"
  [[ -s "$target" ]] || fetch "$BASE/$dir/hist.tab" "$target"
done
for dir in $(python3 "$HELPER" selected); do
  fetch "$BASE/?list-type=2&prefix=$dir/" "$OUT/selected/${dir/\//_}.xml"
done
fetch "$BASE/?list-type=2&prefix=mg_0046/label/" "$OUT/selected/mg_0046_label.xml"

python3 "$HELPER" plan --output-dir "$OUT" --fmidr-dirs "$OUT/fmidr_dirs.txt" \
  --pinned "$RECIPE_DIR/sources.tsv"
echo "[$(date -Is)] discovery done dataset=$DATASET_ID"
