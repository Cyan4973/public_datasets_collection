#!/usr/bin/env bash
# Fetch the 92 pinned SHOALS-1000T COPC tiles of NOAA Digital Coast project
# 8526 (113,122,575 bytes) plus the project metadata XML (70,290 bytes).
# Every file is checked against its pinned size and MD5 (single-part S3 ETag)
# and, once pinned, SHA-256; then every tile header is validated (LAS 1.4,
# compressed PDRF 6, 30-byte records, adjusted-standard GPS time, LASzip
# layered POINT14 v3, COPC info VLR, point count = STAC pc:count).
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in /*) DATA_ROOT="$DATA_DIR" ;; *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;; esac
DATASET_ID="noaa_shoals1000t_bluehillbay_topobathy_gps_time_f64"
DOWNLOAD_DIR="$DATA_ROOT/downloads/$DATASET_ID"
TILE_DIR="$DOWNLOAD_DIR/copc"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"
BASE_URL="https://noaa-nos-coastal-lidar-pds.s3.amazonaws.com"
UA="openzl-public-datasets/1.0 ($DATASET_ID)"
EXPECTED_TILES=92
EXPECTED_TILE_BYTES=113122575
META_KEY="laz/geoid18/8526/metadata_me2017_blue_hill_bay_shoals.xml"
META_SIZE=70290
META_MD5="65e8667753e6b5755af71e5118c35b27"
META_SHA256="da905610f5edfeb3f0f562fb4899edb16394ade5c88193e396e1a3eb9d1beedc"

mkdir -p "$TILE_DIR" "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/download.$RUN_TS.log" "$LOG_DIR/download.latest.log") 2>&1
echo "[$(date -Is)] download start dataset=$DATASET_ID data_root=$DATA_ROOT"

# Liveness: one-byte range GET on the first pinned tile.
first_key="$(awk -F'\t' 'NR==2 {print $1}' "$RECIPE_DIR/sources.tsv")"
curl -fsSL --max-time 60 --retry 3 --retry-delay 5 -r 0-0 -o /dev/null \
  --user-agent "$UA" "$BASE_URL/$first_key"

fetch() {
  # fetch <url> <target> <size> <md5> <sha256-or-empty>
  local url="$1" target="$2" size="$3" md5="$4" sha="$5" actual
  if [[ -f "$target" && "$(stat -c %s "$target")" == "$size" ]] \
     && [[ "$(md5sum "$target" | awk '{print $1}')" == "$md5" ]]; then
    echo "cache_hit bytes=$size file=$(basename "$target")"
  else
    rm -f "$target"
    if [[ -f "$target.part" && "$(stat -c %s "$target.part")" -gt "$size" ]]; then
      rm -f "$target.part"
    fi
    echo "fetch bytes=$size url=$url"
    curl -fL -C - --retry 10 --retry-delay 5 --retry-all-errors \
      --speed-limit 1024 --speed-time 120 --max-filesize $((size + 1)) \
      --silent --show-error --user-agent "$UA" -o "$target.part" "$url"
    actual="$(stat -c %s "$target.part")"
    if [[ "$actual" != "$size" ]]; then
      echo "size mismatch file=$(basename "$target") expected=$size actual=$actual" >&2
      rm -f "$target.part"
      exit 1
    fi
    if [[ "$(md5sum "$target.part" | awk '{print $1}')" != "$md5" ]]; then
      echo "MD5 (S3 ETag) mismatch file=$(basename "$target")" >&2
      rm -f "$target.part"
      exit 1
    fi
    mv "$target.part" "$target"
  fi
  actual="$(sha256sum "$target" | awk '{print $1}')"
  if [[ -n "$sha" && "$actual" != "$sha" ]]; then
    echo "SHA-256 mismatch file=$(basename "$target") expected=$sha actual=$actual" >&2
    exit 1
  fi
  LAST_SHA256="$actual"
}

inventory="$DOWNLOAD_DIR/download_inventory.tsv"
printf 'key\tfilename\tsize_bytes\tmd5\tsha256\turl\n' > "$inventory.tmp"

fetch "$BASE_URL/$META_KEY" "$DOWNLOAD_DIR/$(basename "$META_KEY")" "$META_SIZE" "$META_MD5" "$META_SHA256"
grep -q "SHOALS-1000T" "$DOWNLOAD_DIR/$(basename "$META_KEY")" || {
  echo "metadata XML does not describe the SHOALS-1000T project" >&2; exit 1; }
printf '%s\t%s\t%s\t%s\t%s\t%s\n' "$META_KEY" "$(basename "$META_KEY")" "$META_SIZE" \
  "$META_MD5" "$LAST_SHA256" "$BASE_URL/$META_KEY" >> "$inventory.tmp"

count=0
bytes=0
while IFS=$'\t' read -r key filename size md5 _modified _points _gmin _gmax _gavg sha; do
  [[ "$key" != "key" ]] || continue
  [[ "$key" == "laz/geoid18/8526/$filename" ]] || { echo "bad key $key" >&2; exit 1; }
  [[ "${sha:--}" != "-" ]] || sha=""
  fetch "$BASE_URL/$key" "$TILE_DIR/$filename" "$size" "$md5" "$sha"
  printf '%s\t%s\t%s\t%s\t%s\t%s\n' "$key" "$filename" "$size" "$md5" "$LAST_SHA256" \
    "$BASE_URL/$key" >> "$inventory.tmp"
  count=$((count + 1))
  bytes=$((bytes + size))
done < "$RECIPE_DIR/sources.tsv"

if [[ "$count" != "$EXPECTED_TILES" || "$bytes" != "$EXPECTED_TILE_BYTES" ]]; then
  echo "unexpected tile set: count=$count bytes=$bytes" >&2
  exit 1
fi
mv "$inventory.tmp" "$inventory"

python3 -I "$RECIPE_DIR/scripts/shoals_gps_time.py" inspect --download-dir "$TILE_DIR"

echo "[$(date -Is)] download done dataset=$DATASET_ID tiles=$count tile_bytes=$bytes inventory=$inventory"
