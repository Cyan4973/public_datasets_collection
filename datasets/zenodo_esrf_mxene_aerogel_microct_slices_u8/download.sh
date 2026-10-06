#!/usr/bin/env bash
# Download the pinned Zenodo metadata (records 4761663, 4764282, 4766087), the
# 11 .txt volume descriptors, and 20 evenly spaced reconstructed axial slices
# from each of the 11 ESRF ID15 micro-CT volumes (.raw, 1381 x 1381 x Z uint8,
# z-major) as exact HTTP byte ranges.
#
# The record/file map, exact .raw sizes, and descriptor checksums live in
# volumes.tsv next to this script. Slice z of a volume is the byte range
# [z*1907161, (z+1)*1907161). curl -C - does not compose with --range, so a
# failed slice is discarded and re-requested (up to SLICE_ATTEMPTS times).
# Network I/O is curl only; Python only checks lengths, headers, statistics
# and hashes of what curl wrote.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in
  /*) DATA_ROOT="$DATA_DIR" ;;
  *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;;
esac
DATASET_ID="zenodo_esrf_mxene_aerogel_microct_slices_u8"
DOWNLOAD_DIR="$DATA_ROOT/downloads/$DATASET_ID"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"
VOLUMES_TSV="$RECIPE_DIR/volumes.tsv"
PINS_FILE="$RECIPE_DIR/slice_sha256.tsv"
CHECK_SLICE="$RECIPE_DIR/scripts/check_slice.py"
CHECK_META="$RECIPE_DIR/scripts/check_metadata.py"
UA="openzl-public-datasets-esrf-mxene-microct/1.0"

SIDE=1381
SLICE_BYTES=$((SIDE * SIDE))   # 1,907,161 uint8 voxels per axial slice
SLICES_PER_VOLUME=20
MARGIN_PCT=5                   # skip ceil(5% of Z) slices at each volume end
EXPECTED_SLICES=220
EXPECTED_SLICE_BYTES=$((EXPECTED_SLICES * SLICE_BYTES))
SLICE_ATTEMPTS="${SLICE_ATTEMPTS:-5}"
RETRY_BACKOFF_S="${RETRY_BACKOFF_S:-15}"
REQUEST_PAUSE_S="${REQUEST_PAUSE_S:-0.6}"   # stay under Zenodo's ~133 requests/minute guest limit

mkdir -p "$DOWNLOAD_DIR/records" "$DOWNLOAD_DIR/descriptors" "$DOWNLOAD_DIR/slices" "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/download.$RUN_TS.log" "$LOG_DIR/download.latest.log") 2>&1
echo "[$(date -Is)] download start dataset=$DATASET_ID slices_per_volume=$SLICES_PER_VOLUME margin_pct=$MARGIN_PCT"

if [ "${FORCE_DOWNLOAD:-0}" = "1" ]; then
  rm -rf "$DOWNLOAD_DIR/records" "$DOWNLOAD_DIR/descriptors" "$DOWNLOAD_DIR/slices" "$DOWNLOAD_DIR/slice_sha256.tsv"
  mkdir -p "$DOWNLOAD_DIR/records" "$DOWNLOAD_DIR/descriptors" "$DOWNLOAD_DIR/slices"
fi

# ------------------------------------------------------------ record metadata
for record in 4761663 4764282 4766087; do
  out="$DOWNLOAD_DIR/records/$record.json"
  rm -f "$out.part"
  curl --fail --silent --show-error --location \
    --retry 5 --retry-delay 5 --retry-all-errors \
    --connect-timeout 30 --max-time 180 --max-filesize 5000000 \
    --user-agent "$UA" --header "Accept: application/json" \
    --output "$out.part" "https://zenodo.org/api/records/$record"
  mv "$out.part" "$out"
  sleep "$REQUEST_PAUSE_S"
done
python3 "$CHECK_META" records "$VOLUMES_TSV" "$DOWNLOAD_DIR/records"

# ------------------------------------------------------------ descriptors
while IFS=$'\t' read -r strain record raw_key raw_url_key raw_bytes raw_md5 zslices txt_key txt_bytes txt_md5 txt_sha; do
  case "$strain" in "#"*|"") continue ;; esac
  out="$DOWNLOAD_DIR/descriptors/$txt_key"
  if [ -s "$out" ] && printf '%s  %s\n' "$txt_sha" "$out" | sha256sum --check --status; then
    echo "cache_hit descriptors/$txt_key"
  else
    rm -f "$out" "$out.part"
    curl --fail --silent --show-error --location \
      --retry 5 --retry-delay 5 --retry-all-errors \
      --connect-timeout 30 --max-time 120 --max-filesize 100000 \
      --user-agent "$UA" --output "$out.part" \
      "https://zenodo.org/api/records/$record/files/$txt_key/content"
    mv "$out.part" "$out"
    sleep "$REQUEST_PAUSE_S"
  fi
done < "$VOLUMES_TSV"
python3 "$CHECK_META" descriptors "$VOLUMES_TSV" "$DOWNLOAD_DIR/descriptors"

# ------------------------------------------------------------ slice ranges
fetch_slice() {
  # args: strain record raw_url_key raw_bytes z
  local strain="$1" record="$2" url_key="$3" total="$4" z="$5"
  local name; name="$(printf 's%s_z%04d.bin' "$strain" "$z")"
  local out="$DOWNLOAD_DIR/slices/$name"
  local headers="$out.headers"
  local start=$((z * SLICE_BYTES))
  local end=$((start + SLICE_BYTES - 1))
  local url="https://zenodo.org/api/records/$record/files/$url_key/content"
  if [ -s "$out" ] && [ -s "$headers" ]; then
    if python3 "$CHECK_SLICE" "$out" "$headers" "$start" "$end" "$total" "$name" "$PINS_FILE"; then
      echo "cache_hit slices/$name"
      return 0
    fi
    echo "cached slices/$name failed validation; refetching"
    rm -f "$out" "$headers"
  fi
  local attempt
  for attempt in $(seq 1 "$SLICE_ATTEMPTS"); do
    rm -f "$out.part" "$headers.part"
    echo "fetch $name record=$record file=$url_key range=$start-$end attempt=$attempt"
    if curl --fail --silent --show-error --location \
         --retry 10 --retry-delay 5 --retry-all-errors \
         --connect-timeout 30 --speed-limit 1024 --speed-time 120 \
         --max-filesize "$((SLICE_BYTES + 4096))" \
         --range "$start-$end" --user-agent "$UA" \
         --dump-header "$headers.part" --output "$out.part" "$url"; then
      if python3 "$CHECK_SLICE" "$out.part" "$headers.part" "$start" "$end" "$total" "$name" "$PINS_FILE"; then
        mv "$headers.part" "$headers"
        mv "$out.part" "$out"
        sleep "$REQUEST_PAUSE_S"
        return 0
      fi
    fi
    echo "slice $name attempt $attempt failed" >&2
    sleep $((attempt * RETRY_BACKOFF_S))
  done
  rm -f "$out.part" "$headers.part"
  echo "FATAL: could not fetch a valid $name after $SLICE_ATTEMPTS attempts" >&2
  return 1
}

while IFS=$'\t' read -r strain record raw_key raw_url_key raw_bytes raw_md5 zslices txt_key txt_bytes txt_md5 txt_sha; do
  case "$strain" in "#"*|"") continue ;; esac
  [ $((zslices * SLICE_BYTES)) = "$raw_bytes" ] \
    || { echo "FATAL: $raw_key: $zslices x $SLICE_BYTES != pinned $raw_bytes" >&2; exit 1; }
  margin=$(( (zslices * MARGIN_PCT + 99) / 100 ))
  lo=$margin
  hi=$((zslices - 1 - margin))
  span=$((hi - lo))
  den=$((SLICES_PER_VOLUME - 1))
  zs=()
  for ((k = 0; k < SLICES_PER_VOLUME; k++)); do
    zs+=($((lo + (k * span + den / 2) / den)))
  done
  echo "volume strain=${strain}% record=$record file='$raw_key' Z=$zslices kept_z=${zs[*]}"
  for z in "${zs[@]}"; do
    fetch_slice "$strain" "$record" "$raw_url_key" "$raw_bytes" "$z" </dev/null
  done
done < "$VOLUMES_TSV"

# ------------------------------------------------------------ realized pins
(
  cd "$DOWNLOAD_DIR/slices"
  printf '# slice\tbytes\tsha256\n'
  for f in s*_z*.bin; do
    printf '%s\t%s\t%s\n' "$f" "$(wc -c < "$f" | tr -d ' ')" "$(sha256sum "$f" | cut -d' ' -f1)"
  done
) > "$DOWNLOAD_DIR/slice_sha256.tsv.part"
mv "$DOWNLOAD_DIR/slice_sha256.tsv.part" "$DOWNLOAD_DIR/slice_sha256.tsv"
n_slices="$(grep -vc '^#' "$DOWNLOAD_DIR/slice_sha256.tsv")"
n_bytes="$(awk -F'\t' '!/^#/ {s += $2} END {print s}' "$DOWNLOAD_DIR/slice_sha256.tsv")"
n_unique="$(awk -F'\t' '!/^#/ {print $3}' "$DOWNLOAD_DIR/slice_sha256.tsv" | sort -u | wc -l | tr -d ' ')"
echo "slices=$n_slices slice_bytes=$n_bytes unique_sha256=$n_unique"
[ "$n_slices" = "$EXPECTED_SLICES" ] && [ "$n_bytes" = "$EXPECTED_SLICE_BYTES" ] && [ "$n_unique" = "$EXPECTED_SLICES" ] \
  || { echo "FATAL: expected $EXPECTED_SLICES unique slices / $EXPECTED_SLICE_BYTES bytes" >&2; exit 1; }
echo "[$(date -Is)] download done dataset=$DATASET_ID"
