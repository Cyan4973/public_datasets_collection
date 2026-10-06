#!/usr/bin/env bash
# Documents how sources.tsv was resolved.  Not part of the download/build
# path: it fetches the two ISDC directory listings, applies the deterministic
# selection rule in scripts/select_days.py, and HEADs each selected file to
# pin its exact Content-Length, Last-Modified and ETag.  Output goes to
# $DATA_DIR/discovery/<id>/sources.discovered.tsv and is diffed against the
# committed sources.tsv (sha256 values there are filled from the first
# verified download, because ISDC publishes no checksum files).
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in /*) DATA_ROOT="$DATA_DIR" ;; *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;; esac
DATASET_ID="gfz_gracefo_fgm_acal_bnec_f64"
BASE_URL="https://isdc-data.gfz.de/grace-fo/MAGNETIC_FIELD/0201"
OUT_DIR="$DATA_ROOT/discovery/$DATASET_ID"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"
UA="openzl-public-datasets-gracefo-fgm-discover/1.0"

mkdir -p "$OUT_DIR" "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/discover.$RUN_TS.log" "$LOG_DIR/discover.latest.log") 2>&1
echo "[$(date -Is)] discover start dataset=$DATASET_ID"

for sat in GF1 GF2; do
  curl --fail --silent --show-error --location --retry 5 --retry-delay 2 \
    --max-time 300 --user-agent "$UA" \
    --output "$OUT_DIR/listing_${sat}_ACAL_CORR.html" "$BASE_URL/$sat/ACAL_CORR/"
done

python3 "$RECIPE_DIR/scripts/select_days.py" \
  --gf1-listing "$OUT_DIR/listing_GF1_ACAL_CORR.html" \
  --gf2-listing "$OUT_DIR/listing_GF2_ACAL_CORR.html" > "$OUT_DIR/selection.tsv"

out="$OUT_DIR/sources.discovered.tsv"
printf 'slot\tdate\tsatellite\tselection\tfilename\tsize_bytes\tlast_modified\tetag\tsha256\turl\n' > "$out"
while IFS=$'\t' read -r slot day sat note filename; do
  url="$BASE_URL/$sat/ACAL_CORR/$filename"
  headers="$(curl --fail --silent --show-error --head --location --retry 5 \
    --retry-delay 2 --max-time 60 --user-agent "$UA" "$url" | tr -d '\r')"
  size="$(printf '%s\n' "$headers" | awk 'tolower($1)=="content-length:"{v=$2} END{print v}')"
  modified="$(printf '%s\n' "$headers" | sed -n 's/^[Ll]ast-[Mm]odified: //p' | tail -n 1)"
  etag="$(printf '%s\n' "$headers" | sed -n 's/^[Ee][Tt]ag: //p' | tail -n 1 | tr -d '"')"
  [[ "$size" =~ ^[0-9]+$ && "$size" -gt 1000000 ]] || { echo "bad size for $url: $size" >&2; exit 1; }
  modified_iso="$(date -u -d "$modified" +%Y-%m-%dT%H:%M:%SZ)"
  printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\n' \
    "$slot" "$day" "$sat" "$note" "$filename" "$size" "$modified_iso" "$etag" "pending" "$url" >> "$out"
done < "$OUT_DIR/selection.tsv"

count=$(( $(wc -l < "$out") - 1 ))
bytes="$(awk -F'\t' 'NR>1{s+=$6} END{print s}' "$out")"
echo "selected_files=$count selected_bytes=$bytes"
if [[ -f "$RECIPE_DIR/sources.tsv" ]]; then
  if diff <(cut -f1-8,10 "$RECIPE_DIR/sources.tsv") <(cut -f1-8,10 "$out") > "$OUT_DIR/sources.diff"; then
    echo "committed sources.tsv matches discovery (columns other than sha256)"
  else
    echo "WARNING: committed sources.tsv differs from discovery; see $OUT_DIR/sources.diff"
  fi
fi
echo "[$(date -Is)] discover done dataset=$DATASET_ID"
