#!/usr/bin/env bash
# Documents how sources.tsv was resolved (run once by the author on 2026-10-08).
# Not part of the download/build path: download.sh reads the pinned sources.tsv.
# Fetches ~25 MB of public metadata (S3 listing pages, the NOAA per-tile minmax
# CSV, and 4 KiB header prefixes of the 50 selected tiles).
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="noaa_coastal_maine_topobathy_classification_u8"
DISC="$REPO_ROOT/$DATA_DIR/discovery/$DATASET_ID"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
BUCKET="https://noaa-nos-coastal-lidar-pds.s3.amazonaws.com"
PROJECT="laz/geoid18/10423"
mkdir -p "$DISC/pages" "$DISC/prefixes" "$LOG_DIR"
exec > >(tee "$LOG_DIR/discover.latest.log") 2>&1
echo "[$(date -Is)] discover start"

tok=""; i=0
while :; do
  i=$((i + 1))
  page="$DISC/pages/page_$(printf %04d "$i").xml"
  if [[ -z "$tok" ]]; then
    curl -fsS --max-time 120 --retry 5 -o "$page" -G "$BUCKET/" \
      --data-urlencode "list-type=2" --data-urlencode "prefix=$PROJECT/block"
  else
    curl -fsS --max-time 120 --retry 5 -o "$page" -G "$BUCKET/" \
      --data-urlencode "list-type=2" --data-urlencode "prefix=$PROJECT/block" \
      --data-urlencode "continuation-token=$tok"
  fi
  tok="$(grep -o '<NextContinuationToken>[^<]*' "$page" | sed 's/<NextContinuationToken>//' || true)"
  [[ -n "$tok" ]] || break
done
echo "listing_pages=$i"

curl -fsS --max-time 300 --retry 5 -o "$DISC/minmax.csv" \
  "$BUCKET/$PROJECT/minmax_2022_ngs_coastalMaine_m10423.csv"

python3 -I "$RECIPE_DIR/scripts/select_tiles.py" --pages "$DISC/pages" \
  --minmax "$DISC/minmax.csv" --out "$DISC/sources.selected.tsv"

tail -n +2 "$DISC/sources.selected.tsv" | while IFS=$'\t' read -r block tile _rest; do
  curl -fsS --max-time 60 --retry 5 -r 0-4095 -o "$DISC/prefixes/${tile//\//__}" \
    "$BUCKET/$PROJECT/$tile"
done
python3 -I "$RECIPE_DIR/scripts/add_header_counts.py" "$DISC/sources.selected.tsv" \
  "$DISC/prefixes" "$DISC/sources.tsv"

# The pinned copy carries an 11th sha256 column added after the first download.
if cmp -s "$DISC/sources.tsv" <(cut -f1-10 "$RECIPE_DIR/sources.tsv"); then
  echo "sources.tsv columns 1-10 reproduced exactly"
else
  echo "sources.tsv differs from the pinned recipe copy (upstream changed?)"
  diff <(cut -f1-10 "$RECIPE_DIR/sources.tsv") "$DISC/sources.tsv" | head -20 || true
fi
echo "[$(date -Is)] discover done"
