#!/usr/bin/env bash
# Fetch the 50 pinned NOAA NGS Coastal Maine topobathy COPC tiles (sources.tsv)
# plus the project metadata XML. Resumable; validates size, S3 multipart ETag,
# LAS 1.4 / PDRF 6 / 30-byte header and pinned point count of every tile.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="noaa_coastal_maine_topobathy_classification_u8"
DOWNLOAD_DIR="$REPO_ROOT/$DATA_DIR/downloads/$DATASET_ID"
TILE_DIR="$DOWNLOAD_DIR/tiles"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
UA="openzl-public-datasets-noaa-maine-topobathy/1.0"
META_URL="https://noaa-nos-coastal-lidar-pds.s3.amazonaws.com/laz/geoid18/10423/metadata_2022_ngs_coastalMaine.xml"
META_SIZE=99264
META_SHA256="6ffc7e3f8c285e98837e42e98de87caf2031ef70def0c8030d2ed0f5dcd14906"
EXPECTED_TILES=50
EXPECTED_BYTES=2076786177

mkdir -p "$TILE_DIR" "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/download.$RUN_TS.log" "$LOG_DIR/download.latest.log") 2>&1
echo "[$(date -Is)] download start dataset=$DATASET_ID"

fetch() {  # url target
  local url="$1" target="$2"
  curl --globoff --fail --silent --show-error --location -C - \
    --retry 10 --retry-delay 5 --retry-all-errors \
    --speed-limit 1024 --speed-time 120 \
    --user-agent "$UA" --output "$target.part" "$url"
  mv "$target.part" "$target"
}

# Project metadata (lineage: sensor, PDRF 6, classification scheme; constraints).
meta="$DOWNLOAD_DIR/metadata_2022_ngs_coastalMaine.xml"
if [[ ! -s "$meta" ]]; then fetch "$META_URL" "$meta"; fi
[[ "$(stat -c %s "$meta")" = "$META_SIZE" ]] || { echo "metadata size mismatch" >&2; exit 1; }
[[ "$(sha256sum "$meta" | awk '{print $1}')" = "$META_SHA256" ]] || { echo "metadata SHA-256 mismatch" >&2; exit 1; }
grep -q "Chiroptera Hawkeye 4X" "$meta" || { echo "metadata lacks sensor lineage" >&2; exit 1; }

plan="$DOWNLOAD_DIR/download_plan.tsv"
printf 'block\ttile\tlocal_file\tsize_bytes\tetag\tpoint_count\tsha256\turl\n' > "$plan.tmp"
count=0
bytes=0
while IFS=$'\t' read -r block tile size etag last_modified min_z max_z qualifying url point_count sha256; do
  [[ "$block" != "block" ]] || continue
  local_name="${tile//\//__}"
  target="$TILE_DIR/$local_name"
  if [[ -s "$target" && "$(stat -c %s "$target")" = "$size" ]]; then
    echo "cache_hit $local_name bytes=$size"
  else
    rm -f "$target"
    echo "fetch $local_name bytes=$size"
    fetch "$url" "$target"
  fi
  if ! actual_sha="$(python3 -I "$RECIPE_DIR/scripts/check_payload.py" "$target" "$size" "$etag" "$point_count" "${sha256:-}")"; then
    echo "invalid payload $local_name; removing it so a re-run refetches" >&2
    mv "$target" "$target.invalid"
    exit 1
  fi
  echo "ok $local_name points=$point_count sha256=$actual_sha"
  printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\n' "$block" "$tile" "tiles/$local_name" "$size" \
    "$etag" "$point_count" "$actual_sha" "$url" >> "$plan.tmp"
  count=$((count + 1))
  bytes=$((bytes + size))
done < "$RECIPE_DIR/sources.tsv"

[[ "$count" = "$EXPECTED_TILES" ]] || { echo "unexpected tile count $count" >&2; exit 1; }
[[ "$bytes" = "$EXPECTED_BYTES" ]] || { echo "unexpected tile bytes $bytes" >&2; exit 1; }
mv "$plan.tmp" "$plan"
echo "[$(date -Is)] download done dataset=$DATASET_ID tiles=$count bytes=$bytes"
