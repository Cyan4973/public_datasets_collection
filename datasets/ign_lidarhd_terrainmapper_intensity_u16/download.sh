#!/usr/bin/env bash
# Fetch the 12 pinned IGN LiDAR HD COPC tiles listed in sources.tsv (mission
# 21LHD2GO, Leica TerrainMapper:90560, delivery NUALHD_1-0__LAZ_LAMB93_GO_2025-09-22).
# Resumable (curl -C -, stall-based abort). Every tile must match the byte
# length and MD5 published in the IGN Atom download feed, and its LAS 1.4 /
# PDRF 6 / COPC header, VLRs, EVLR directory and header point count must match
# the pinned values; SHA-256 (pinned in sources.tsv after the first download)
# must match too and is recorded in download_inventory.tsv.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in /*) ROOT="$DATA_DIR" ;; *) ROOT="$REPO_ROOT/$DATA_DIR" ;; esac
DATASET_ID="ign_lidarhd_terrainmapper_intensity_u16"
DOWNLOAD_DIR="$ROOT/downloads/$DATASET_ID"
TILE_DIR="$DOWNLOAD_DIR/tiles"
LOG_DIR="$ROOT/logs/$DATASET_ID"
UA="openzl-public-datasets-ign-lidarhd/1.0"
DELIVERY_PREFIX="https://data.geopf.fr/telechargement/download/LiDARHD-NUALID/NUALHD_1-0__LAZ_LAMB93_GO_2025-09-22/"
EXPECTED_TILES=12
EXPECTED_BYTES=2071849594

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

inventory="$DOWNLOAD_DIR/download_inventory.tsv"
printf 'tile\tsize_bytes\tmd5\tsha256\theader_point_count\turl\n' > "$inventory.tmp"
count=0
bytes=0
while IFS=$'\t' read -r tile nw pts size md5 d0 d1 url hdr_points sha_pinned; do
  [[ "$tile" != "tile" ]] || continue
  [[ "$url" == "$DELIVERY_PREFIX$tile" ]] || { echo "unexpected url for $tile: $url" >&2; exit 1; }
  target="$TILE_DIR/$tile"
  if [[ -f "$target" && "$(stat -L -c %s "$target")" == "$size" ]]; then
    echo "cache_hit $tile bytes=$size"
  else
    rm -f "$target"
    if [[ -f "$target.part" && "$(stat -L -c %s "$target.part")" -gt "$size" ]]; then rm -f "$target.part"; fi
    echo "[$(date -Is)] fetch $tile bytes=$size"
    sleep 1  # the download service allows 1 request/s
    fetch "$url" "$target" < /dev/null
  fi
  actual_size="$(stat -L -c %s "$target")"
  actual_md5="$(md5sum "$target" | awk '{print $1}')"
  if [[ "$actual_size" != "$size" || "$actual_md5" != "$md5" ]]; then
    echo "size/MD5 mismatch for $tile: got $actual_size $actual_md5, pinned $size $md5" >&2
    mv "$target" "$target.invalid"
    exit 1
  fi
  if ! python3 -I "$RECIPE_DIR/scripts/ign_intensity.py" check --laz-dir "$REPO_ROOT/tools/laz" "$target" "$hdr_points" < /dev/null; then
    echo "invalid LAS/COPC payload $tile; moved aside so a re-run refetches" >&2
    mv "$target" "$target.invalid"
    exit 1
  fi
  sha="$(sha256sum "$target" | awk '{print $1}')"
  if [[ -n "${sha_pinned:-}" && "$sha" != "$sha_pinned" ]]; then
    echo "SHA-256 mismatch for $tile: got $sha, pinned $sha_pinned" >&2
    mv "$target" "$target.invalid"
    exit 1
  fi
  echo "ok $tile md5=$actual_md5 sha256=$sha"
  printf '%s\t%s\t%s\t%s\t%s\t%s\n' "$tile" "$size" "$md5" "$sha" "$hdr_points" "$url" >> "$inventory.tmp"
  count=$((count + 1))
  bytes=$((bytes + size))
done < "$RECIPE_DIR/sources.tsv"

[[ "$count" == "$EXPECTED_TILES" ]] || { echo "unexpected tile count $count" >&2; exit 1; }
[[ "$bytes" == "$EXPECTED_BYTES" ]] || { echo "unexpected total bytes $bytes" >&2; exit 1; }
mv "$inventory.tmp" "$inventory"
echo "[$(date -Is)] download done dataset=$DATASET_ID tiles=$count bytes=$bytes"
