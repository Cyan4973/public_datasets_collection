#!/usr/bin/env bash
# Fetch the 22 pinned Cassini RADAR BIBQH (Titan, 128 pix/deg, 8-bit dB sigma0)
# product ZIPs (89,704,750 bytes total) from the public USGS PDS Cassini S3
# bucket, then reject anything that is not the pinned, label-consistent
# uint8 BIDR image.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in /*) DATA_ROOT="$DATA_DIR" ;; *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;; esac
DATASET_ID="nasa_pds_cassini_radar_bidr_sigma0_u8"
DOWNLOAD_DIR="$DATA_ROOT/downloads/$DATASET_ID"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"
PLAN="$DOWNLOAD_DIR/download_plan.tsv"
mkdir -p "$DOWNLOAD_DIR" "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/download.$RUN_TS.log" "$LOG_DIR/download.latest.log") 2>&1
echo "[$(date -Is)] download start dataset=$DATASET_ID data_root=$DATA_ROOT"

python3 "$RECIPE_DIR/scripts/recipe.py" plan --sources "$RECIPE_DIR/sources.tsv" --out "$PLAN"

md5_of() { md5sum "$1" | awk '{print $1}'; }

# Liveness check on the first object: one-byte range GET.
first_url="$(awk -F'\t' 'NR==2 {print $3}' "$PLAN")"
curl --fail --silent --show-error --location --max-time 60 --range 0-0 --output /dev/null "$first_url"

while IFS=$'\t' read -r ordinal local_filename url zip_bytes zip_md5; do
  [[ "$ordinal" == "ordinal" ]] && continue
  target="$DOWNLOAD_DIR/$local_filename"
  part="$target.part"
  if [[ -f "$target" && "$(stat -c %s "$target")" == "$zip_bytes" && "${FORCE_DOWNLOAD:-0}" != "1" ]]; then
    echo "cache_hit ordinal=$ordinal file=$local_filename"
  else
    rm -f "$target"
    if [[ -f "$part" && "$(stat -c %s "$part")" -gt "$zip_bytes" ]]; then rm -f "$part"; fi
    attempt=0
    while [[ ! -f "$part" || "$(stat -c %s "$part")" -lt "$zip_bytes" ]]; do
      attempt=$((attempt + 1))
      if (( attempt > 8 )); then echo "giving up on $local_filename" >&2; exit 1; fi
      echo "fetch ordinal=$ordinal file=$local_filename bytes=$zip_bytes attempt=$attempt"
      curl --fail --location --silent --show-error -C - --retry 10 --retry-delay 5 \
        --speed-limit 1024 --speed-time 120 --max-filesize 100000000 \
        --output "$part" "$url" || sleep 5
    done
    [[ "$(stat -c %s "$part")" == "$zip_bytes" ]] || { echo "size mismatch: $local_filename" >&2; rm -f "$part"; exit 1; }
    mv "$part" "$target"
  fi
  if [[ "$(md5_of "$target")" != "$zip_md5" ]]; then
    echo "MD5 mismatch vs pinned S3 ETag: $local_filename (removed)" >&2
    rm -f "$target"
    exit 1
  fi
done < "$PLAN"

# Semantic validation: single DEFLATE member named <product>.IMG with pinned
# size/CRC32, decoded IMG MD5 equal to the S3 ETag of the uncompressed .IMG,
# attached PDS3 label = pinned geometry + Titan/BIBQH family constants,
# FILE_RECORDS consistency, label CHECKSUM = sum of image bytes, nonconstant.
python3 "$RECIPE_DIR/scripts/recipe.py" validate --sources "$RECIPE_DIR/sources.tsv" --download-dir "$DOWNLOAD_DIR"

du -sb "$DOWNLOAD_DIR" | awk '{print "download_dir_bytes=" $1}'
echo "[$(date -Is)] download done dataset=$DATASET_ID"
