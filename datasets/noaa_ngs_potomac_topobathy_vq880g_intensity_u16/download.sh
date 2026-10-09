#!/usr/bin/env bash
# Fetch the 48 pinned NOAA NGS 2018 Potomac River / Chesapeake Bay topobathy
# COPC tiles (sources.tsv) plus the project metadata XML. Resumable curl;
# every tile is validated for size, S3 ETag (content MD5), LAS 1.4 / PDRF 7 /
# 36-byte records and the pinned point count; SHA-256s are recorded.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in /*) DATA_ROOT="$DATA_DIR" ;; *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;; esac
DATASET_ID="noaa_ngs_potomac_topobathy_vq880g_intensity_u16"
DOWNLOAD_DIR="$DATA_ROOT/downloads/$DATASET_ID"
TILE_DIR="$DOWNLOAD_DIR/tiles"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"
UA="openzl-public-datasets-noaa-potomac-topobathy/1.0"
META_URL="https://noaa-nos-coastal-lidar-pds.s3.amazonaws.com/laz/geoid18/8727/metadata_2018_ngs_topobathy_potomac_river_chesapeake.xml"
META_SIZE=71682
META_SHA256="7cbc2f77381f20f7fabea88a2db669085e5f2575f678aaec37222bea74849000"
EXPECTED_TILES=48
EXPECTED_BYTES=868443284

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

# Project metadata (lineage: Riegl VQ-880-G green+NIR, QSI processing, constraints).
meta="$DOWNLOAD_DIR/metadata_2018_ngs_topobathy_potomac_river_chesapeake.xml"
if [[ ! -s "$meta" || "$(stat -c %s "$meta")" != "$META_SIZE" ]]; then
  rm -f "$meta"
  fetch "$META_URL" "$meta"
fi
[[ "$(stat -c %s "$meta")" = "$META_SIZE" ]] || { echo "metadata size mismatch" >&2; exit 1; }
[[ "$(sha256sum "$meta" | awk '{print $1}')" = "$META_SHA256" ]] || { echo "metadata SHA-256 mismatch" >&2; exit 1; }
grep -q "Riegl VQ880G" "$meta" || { echo "metadata lacks sensor lineage" >&2; exit 1; }
grep -q "Access Constraints: None" "$meta" || { echo "metadata lacks access-constraint statement" >&2; exit 1; }

plan="$DOWNLOAD_DIR/download_plan.tsv"
printf 'delivery\ttile\tlocal_file\tsize_bytes\tetag\tpoint_count\tsha256\turl\n' > "$plan.tmp"
count=0
bytes=0
while IFS=$'\t' read -r delivery tile size etag last_modified url point_count sha256; do
  [[ "$delivery" != "delivery" ]] || continue
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
    echo "invalid payload $local_name; moved aside so a re-run refetches" >&2
    mv "$target" "$target.invalid"
    exit 1
  fi
  echo "ok $local_name points=$point_count sha256=$actual_sha"
  printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\n' "$delivery" "$tile" "tiles/$local_name" "$size" \
    "$etag" "$point_count" "$actual_sha" "$url" >> "$plan.tmp"
  count=$((count + 1))
  bytes=$((bytes + size))
done < "$RECIPE_DIR/sources.tsv"

[[ "$count" = "$EXPECTED_TILES" ]] || { echo "unexpected tile count $count" >&2; exit 1; }
[[ "$bytes" = "$EXPECTED_BYTES" ]] || { echo "unexpected tile bytes $bytes" >&2; exit 1; }
mv "$plan.tmp" "$plan"
echo "[$(date -Is)] download done dataset=$DATASET_ID tiles=$count bytes=$bytes"
