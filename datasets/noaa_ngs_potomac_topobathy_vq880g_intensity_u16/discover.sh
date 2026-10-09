#!/usr/bin/env bash
# Documents how sources.tsv was resolved (run by the author on 2026-10-08).
# Not part of the download/build path: download.sh reads the pinned sources.tsv.
# Network use: 12 anonymous S3 ListObjectsV2 pages (~5 MB) plus byte-range GETs
# of header, chunk table and five LASzip chunks per selected tile (~2-3 MB per
# tile) for the decode probe. No complete tile is downloaded.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in /*) DATA_ROOT="$DATA_DIR" ;; *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;; esac
DATASET_ID="noaa_ngs_potomac_topobathy_vq880g_intensity_u16"
DISC="$DATA_ROOT/discovery/$DATASET_ID"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"
BUCKET="https://noaa-nos-coastal-lidar-pds.s3.amazonaws.com"
PREFIX="laz/geoid18/8727/"
mkdir -p "$DISC/pages" "$LOG_DIR"
exec > >(tee "$LOG_DIR/discover.latest.log") 2>&1
echo "[$(date -Is)] discover start"

rm -f "$DISC"/pages/*.xml
tok=""; i=0
while :; do
  i=$((i + 1))
  page="$DISC/pages/page_$(printf %04d "$i").xml"
  args=(-G "$BUCKET/" --data-urlencode "list-type=2" --data-urlencode "prefix=$PREFIX")
  [[ -z "$tok" ]] || args+=(--data-urlencode "continuation-token=$tok")
  curl -fsS --max-time 120 --retry 5 -o "$page" "${args[@]}"
  tok="$(grep -o '<NextContinuationToken>[^<]*' "$page" | sed 's/<NextContinuationToken>//' || true)"
  [[ -n "$tok" ]] || break
done
echo "listing_pages=$i"

# 2026-10-08: no tile needed excluding (all 48 decoded); failed tiles would be
# passed here as --exclude deliveryNN/<name>.copc.laz and documented in README.
python3 -I "$RECIPE_DIR/scripts/select_tiles.py" "$DISC/pages" "$DISC/selected.tsv"
python3 -I "$RECIPE_DIR/scripts/probe_decode.py" "$DISC/selected.tsv" "$DISC/probe_work" \
  "$REPO_ROOT/tools/laz" "$DISC/probe.tsv" --jobs "${JOBS:-8}"

if cmp -s "$DISC/selected.tsv" <(cut -f1-6 "$RECIPE_DIR/sources.tsv"); then
  echo "sources.tsv columns 1-6 reproduced exactly"
else
  echo "selection differs from the pinned sources.tsv (upstream changed?)"
  diff <(cut -f1-6 "$RECIPE_DIR/sources.tsv") "$DISC/selected.tsv" | head -20 || true
fi
echo "[$(date -Is)] discover done"
