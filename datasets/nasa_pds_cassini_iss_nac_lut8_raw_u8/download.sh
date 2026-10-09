#!/usr/bin/env bash
# Fetch the 314 pinned Cassini ISS narrow-angle TABLE/FULL/LOSSLESS EDR frames listed in
# sources.tsv (COISS_2050-2052), the three volume indexes (selection evidence) and the
# COISS_2050 aareadme.txt (citation evidence) from the PDS Imaging Node.
set -euo pipefail

RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$RECIPE_DIR/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in /*) DATA_ROOT="$DATA_DIR" ;; *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;; esac
DATASET_ID="nasa_pds_cassini_iss_nac_lut8_raw_u8"
DOWNLOAD_DIR="$DATA_ROOT/downloads/$DATASET_ID"
RAW_DIR="$DOWNLOAD_DIR/raw"
INDEX_DIR="$DOWNLOAD_DIR/index"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"
SOURCES="$RECIPE_DIR/sources.tsv"
CHECK="$RECIPE_DIR/scripts/check_payload.py"
BASE="https://planetarydata.jpl.nasa.gov/img/data/cassini/cassini_orbiter"
UA="openzl-public-datasets-cassini-iss/1.0"
EXPECTED_FRAMES=314
EXPECTED_IMG_BYTES=338286016

mkdir -p "$RAW_DIR" "$INDEX_DIR" "$DOWNLOAD_DIR/evidence" "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/download.$RUN_TS.log" "$LOG_DIR/download.latest.log") 2>&1
echo "[$(date -Is)] download start dataset=$DATASET_ID data_root=$DATA_ROOT"

md5_of() { md5sum "$1" | cut -d' ' -f1; }

# fetch_pinned <url> <target> <size> <md5> <max_bytes>: resumable fetch validated by size and MD5.
fetch_pinned() {
  local url="$1" target="$2" size="$3" md5="$4" max="$5"
  if [[ -s "$target" && "$(stat -c %s "$target")" == "$size" && "$(md5_of "$target")" == "$md5" ]]; then
    return 0
  fi
  rm -f "$target"
  if [[ -s "$target.part" ]] && (( $(stat -c %s "$target.part") > size )); then
    rm -f "$target.part"
  fi
  curl --fail --silent --show-error --location -C - \
    --retry 10 --retry-delay 5 --retry-all-errors \
    --speed-limit 1024 --speed-time 120 --max-filesize "$max" \
    --user-agent "$UA" --output "$target.part" "$url"
  local actual
  actual="$(stat -c %s "$target.part")"
  if [[ "$actual" != "$size" || "$(md5_of "$target.part")" != "$md5" ]]; then
    echo "FATAL size/MD5 mismatch for $url (expected $size / $md5, got $actual bytes)" >&2
    rm -f "$target.part"
    exit 1
  fi
  mv "$target.part" "$target"
}

# Liveness: one-byte range GET on the first pinned frame.
first_url="$(awk -F'\t' 'NR==2 {print $11}' "$SOURCES")"
curl --fail --silent --show-error --location --max-time 60 --range 0-0 \
  --user-agent "$UA" --output /dev/null "$first_url"
echo "liveness_ok url=$first_url"

# Citation evidence (MD5 from the PDS Rings Node COISS_2050 checksum manifest).
fetch_pinned "$BASE/coiss_2050/aareadme.txt" "$DOWNLOAD_DIR/evidence/aareadme.txt" \
  34646 2b965e25c8b0eb3ffb9b39cc6f8c7e23 1000000
python3 "$CHECK" evidence "$DOWNLOAD_DIR/evidence/aareadme.txt"

# Volume indexes (selection evidence), pinned by size and Rings Node MD5.
fetch_pinned "$BASE/coiss_2050/index/index.lbl" "$INDEX_DIR/COISS_2050_index.lbl" 48126 d905643b009d4d599dfb0e9902dd8f7a 1000000
fetch_pinned "$BASE/coiss_2050/index/index.tab" "$INDEX_DIR/COISS_2050_index.tab" 13637277 a959489da5ec089434d0dd39a5b51940 30000000
fetch_pinned "$BASE/coiss_2051/index/index.lbl" "$INDEX_DIR/COISS_2051_index.lbl" 48124 5cfd99179a59ac532b987ad1856b38ff 1000000
fetch_pinned "$BASE/coiss_2051/index/index.tab" "$INDEX_DIR/COISS_2051_index.tab" 2934720 1a19657947023e946b25ec9e59a1d573 30000000
fetch_pinned "$BASE/coiss_2052/index/index.lbl" "$INDEX_DIR/COISS_2052_index.lbl" 48079 2626099b089f1b5670bd89ef7ec7c99f 1000000
fetch_pinned "$BASE/coiss_2052/index/index.tab" "$INDEX_DIR/COISS_2052_index.tab" 16691220 31111cf8ec7da7620ef81533f0bf4afb 30000000
python3 "$CHECK" index "$INDEX_DIR" "$SOURCES"

plan="$DOWNLOAD_DIR/download_plan.tsv"
printf 'volume\tproduct\timage_number\timg_size\timg_md5\timg_sha256\n' > "$plan.part"
count=0
img_bytes=0
fetched=0
while IFS='|' read -r volume product image_number img_url img_size img_md5; do
  img="$RAW_DIR/${volume}_${product}.IMG"
  had=0
  [[ -s "$img" ]] && had=1
  fetch_pinned "$img_url" "$img" "$img_size" "$img_md5" 2000000
  if ! digests="$(python3 "$CHECK" frame "$img" "$product" "$image_number")"; then
    echo "FATAL semantic validation failed volume=$volume product=$product" >&2
    rm -f "$img"
    exit 1
  fi
  if [[ "${digests%% *}" != "$img_md5" ]]; then
    echo "FATAL MD5 mismatch after decode check product=$product" >&2
    exit 1
  fi
  if [[ "$had" == 0 ]]; then
    fetched=$((fetched + 1))
    echo "fetched volume=$volume product=$product md5=$img_md5"
  fi
  printf '%s\t%s\t%s\t%s\t%s\t%s\n' "$volume" "$product" "$image_number" "$img_size" "$img_md5" "${digests##* }" >> "$plan.part"
  count=$((count + 1))
  img_bytes=$((img_bytes + img_size))
done < <(awk -F'\t' 'NR > 1 {print $1 "|" $3 "|" $4 "|" $11 "|" $12 "|" $13}' "$SOURCES")
mv "$plan.part" "$plan"

if [[ "$count" != "$EXPECTED_FRAMES" || "$img_bytes" != "$EXPECTED_IMG_BYTES" ]]; then
  echo "FATAL unexpected selection totals frames=$count img_bytes=$img_bytes" \
    "(expected $EXPECTED_FRAMES / $EXPECTED_IMG_BYTES)" >&2
  exit 1
fi
echo "[$(date -Is)] download done dataset=$DATASET_ID frames=$count img_bytes=$img_bytes fetched_now=$fetched"
