#!/usr/bin/env bash
# Download the 15 pinned swissSURFACE3D 2021 tile zips listed in sources.tsv
# from data.geo.admin.ch (swisstopo STAC asset hrefs, anonymous HTTPS).
#
# Each zip is fetched resumably into a .part file, then checked against the
# pinned byte size and the SHA-256 published as the STAC asset
# checksum:multihash (0x1220 = sha2-256). After that, every zip is checked for
# meaning: exactly one deflated member <E>_<N>.las whose size equals
# 227 + 28 * point_count and whose CRC-32 matches the pinned value. The member
# must have a LAS 1.2 header (LAStools las2las, point format 1, 28-byte
# records, no VLRs, scale 0.01, offsets = tile corner/0, pinned point count and
# Z bounds), and the member is fully inflated so zipfile enforces the CRC-32.
# Re-runs skip validated zips and resume partial .part files.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in /*) DATA_ROOT="$DATA_DIR" ;; *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;; esac
DATASET_ID="swisstopo_swisssurface3d_alps_las_z_i32"
DOWNLOAD_DIR="$DATA_ROOT/downloads/$DATASET_ID/zip"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"
SOURCES="$RECIPE_DIR/sources.tsv"
TOOL="$RECIPE_DIR/scripts/las_z.py"
UA="openzl-public-datasets/1.0"
CURL_COMMON=(--fail --silent --show-error --location --retry 10 --retry-delay 5 --retry-all-errors
  --speed-limit 1024 --speed-time 120 --user-agent "$UA")

mkdir -p "$DOWNLOAD_DIR" "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/download.$RUN_TS.log" "$LOG_DIR/download.latest.log") 2>&1
echo "[$(date -Is)] download start dataset=$DATASET_ID"

python3 -I "$TOOL" self-test

check_zip() {
  local path="$1" size="$2" sha="$3"
  [[ -f "$path" ]] || return 1
  [[ "$(stat -c %s "$path")" == "$size" ]] || return 1
  [[ "$(sha256sum "$path" | cut -d' ' -f1)" == "$sha" ]]
}

# Liveness: one-byte range GET on the first pinned asset.
first_url="$(awk -F'\t' 'NR==2{print $3}' "$SOURCES")"
curl "${CURL_COMMON[@]}" --max-time 120 --range 0-0 --output /dev/null "$first_url"
echo "liveness=ok"

total=0
while IFS=$'\t' read -r item_id asset_name url zip_bytes sha256 _rest; do
  [[ "$item_id" == "item_id" ]] && continue
  target="$DOWNLOAD_DIR/$asset_name"
  total=$((total + zip_bytes))
  if check_zip "$target" "$zip_bytes" "$sha256"; then
    echo "validated existing $asset_name"
    continue
  fi
  rm -f "$target"
  ok=0
  for attempt in 1 2 3; do
    echo "fetch $url (attempt $attempt)"
    if curl "${CURL_COMMON[@]}" --continue-at - --output "$target.part" "$url"; then
      ok=1; break
    fi
    # A 416 on a complete .part also lands here; fall through to the size check.
    if [[ -f "$target.part" && "$(stat -c %s "$target.part")" == "$zip_bytes" ]]; then
      ok=1; break
    fi
    sleep $((attempt * 15))
  done
  [[ "$ok" == 1 ]] || { echo "FATAL: download failed for $asset_name" >&2; exit 1; }
  got_size="$(stat -c %s "$target.part")"
  if [[ "$got_size" != "$zip_bytes" ]]; then
    echo "FATAL: $asset_name size $got_size != pinned $zip_bytes" >&2
    [[ "$got_size" -gt "$zip_bytes" ]] && rm -f "$target.part"
    exit 1
  fi
  got_sha="$(sha256sum "$target.part" | cut -d' ' -f1)"
  if [[ "$got_sha" != "$sha256" ]]; then
    echo "FATAL: $asset_name sha256 $got_sha != pinned $sha256" >&2
    rm -f "$target.part"
    exit 1
  fi
  mv "$target.part" "$target"
  echo "downloaded $asset_name bytes=$zip_bytes sha256=ok"
done < "$SOURCES"

python3 -I "$TOOL" validate --sources "$SOURCES" --download-dir "$DOWNLOAD_DIR"

cp "$SOURCES" "$DATA_ROOT/downloads/$DATASET_ID/download_inventory.tsv"
echo "[$(date -Is)] download done dataset=$DATASET_ID zip_bytes=$total"
