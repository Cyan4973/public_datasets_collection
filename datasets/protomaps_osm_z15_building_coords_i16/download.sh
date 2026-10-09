#!/usr/bin/env bash
# Fetch only pinned byte ranges of the Protomaps 20250120 planet PMTiles build:
# the header/root-directory region, the metadata JSON, 72 leaf directories, and
# one contiguous tile-data span per fixed city-centre 8x8 z15 block (blocks.tsv).
# The 129.6 GB archive itself is never downloaded.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in /*) DATA_ROOT="$DATA_DIR" ;; *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;; esac
DATASET_ID="protomaps_osm_z15_building_coords_i16"
DOWNLOAD_DIR="$DATA_ROOT/downloads/$DATASET_ID"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"
URL="https://build.protomaps.com/20250120.pmtiles"
ARCHIVE_SIZE=129605595792
ETAG='"421a670075e8b7e6147fbab946c5a264-483"'
METADATA_OFFSET=129274242420
METADATA_LENGTH=1155
PY="python3 -I $RECIPE_DIR/scripts/recipe.py"

mkdir -p "$DOWNLOAD_DIR/leaves" "$DOWNLOAD_DIR/spans" "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/download.$RUN_TS.log" "$LOG_DIR/download.latest.log") 2>&1
echo "[$(date -Is)] download start dataset=$DATASET_ID url=$URL"

CURL=(curl --fail --location --silent --show-error --retry 10 --retry-delay 5
      --retry-all-errors --speed-limit 1024 --speed-time 120)

# Liveness + identity: one-byte range GET; total size and ETag must match the pinned build.
hdrs="$("${CURL[@]}" -r 0-0 -D - -o /dev/null "$URL" | tr -d '\r')"
grep -qi "^content-range: bytes 0-0/$ARCHIVE_SIZE\$" <<<"$hdrs" || {
  echo "archive size changed or range requests unsupported:"; echo "$hdrs"; exit 1; }
grep -qiF "etag: $ETAG" <<<"$hdrs" || { echo "archive ETag changed:"; echo "$hdrs"; exit 1; }
echo "archive identity ok: size=$ARCHIVE_SIZE etag=$ETAG"

# fetch_range OUT ABS_OFFSET LENGTH: exact byte range into OUT (skips if complete).
fetch_range() {
  local out="$1" off="$2" len="$3"
  if [[ -f "$out" && "$(stat -c %s "$out")" == "$len" ]]; then
    return 0
  fi
  local attempt
  for attempt in 1 2 3; do
    rm -f "$out.part"
    if "${CURL[@]}" -r "${off}-$((off + len - 1))" -o "$out.part" "$URL" </dev/null &&
       [[ "$(stat -c %s "$out.part")" == "$len" ]]; then
      mv "$out.part" "$out"
      return 0
    fi
    echo "retrying range $off+$len (attempt $attempt failed)"
    sleep 5
  done
  echo "failed to fetch range $off+$len into $out"; return 1
}

fetch_range "$DOWNLOAD_DIR/header_root.bin" 0 16384
fetch_range "$DOWNLOAD_DIR/metadata.json.gz" "$METADATA_OFFSET" "$METADATA_LENGTH"
$PY check-header "$DOWNLOAD_DIR" "$RECIPE_DIR"

# Leaf directories (pinned sizes and SHA-256 in leaves.tsv).
n_leaves=0
while IFS=$'\t' read -r rel abs len sha; do
  [[ "$rel" == "leaf_rel_offset" ]] && continue
  out="$DOWNLOAD_DIR/leaves/leaf_${rel}.gz"
  fetch_range "$out" "$abs" "$len"
  if [[ "$(sha256sum "$out" | cut -d' ' -f1)" != "$sha" ]]; then
    echo "leaf $rel SHA-256 mismatch"; rm -f "$out"; exit 1
  fi
  n_leaves=$((n_leaves + 1))
done < "$RECIPE_DIR/leaves.tsv"
echo "leaf directories verified: $n_leaves"

# Tile-data spans: one contiguous range per block; validated by size, optional
# pinned SHA-256, gzip magic, and MVT decoding of every tile in the span.
: > "$DOWNLOAD_DIR/span_sha256.tsv.part"
n_spans=0
total=0
while IFS=$'\t' read -r block_id city continent z x0 y0 first_tid leaf_offs span_off span_len n_in n_out span_sha; do
  [[ "$block_id" == "block_id" ]] && continue
  out="$DOWNLOAD_DIR/spans/${block_id}.bin"
  fetch_range "$out" "$span_off" "$span_len"
  if ! line="$($PY check-span "$DOWNLOAD_DIR" "$RECIPE_DIR" "$block_id" "$out" </dev/null)"; then
    echo "span $block_id failed validation; removing"; rm -f "$out"; exit 1
  fi
  echo "$line"
  printf '%s\n' "$line" | cut -f1,2 >> "$DOWNLOAD_DIR/span_sha256.tsv.part"
  n_spans=$((n_spans + 1))
  total=$((total + span_len))
done < "$RECIPE_DIR/blocks.tsv"
mv "$DOWNLOAD_DIR/span_sha256.tsv.part" "$DOWNLOAD_DIR/span_sha256.tsv"
echo "spans verified: $n_spans ($total bytes)"
echo "[$(date -Is)] download done dataset=$DATASET_ID"
