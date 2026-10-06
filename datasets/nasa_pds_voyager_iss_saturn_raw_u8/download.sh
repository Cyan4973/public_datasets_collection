#!/usr/bin/env bash
# Fetch the 339 pinned Voyager 2 narrow-angle Saturn-encounter raw frames
# (VGISS_0005 Cnnnnnnn_RAW.IMG + detached .LBL) listed in sources.tsv, plus the
# volume index (selection evidence) and AAREADME (citation/rights evidence),
# all from the public anonymous asc-pds-voyager S3 bucket.
set -euo pipefail

RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$RECIPE_DIR/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in /*) DATA_ROOT="$DATA_DIR" ;; *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;; esac
DATASET_ID="nasa_pds_voyager_iss_saturn_raw_u8"
DOWNLOAD_DIR="$DATA_ROOT/downloads/$DATASET_ID"
RAW_DIR="$DOWNLOAD_DIR/raw"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"
SOURCES="$RECIPE_DIR/sources.tsv"
CHECK="$RECIPE_DIR/scripts/check_payload.py"
BASE="https://asc-pds-voyager.s3.us-west-2.amazonaws.com/VGISS_0005"
UA="openzl-public-datasets-voyager-iss/1.0"
EXPECTED_FRAMES=339
EXPECTED_IMG_BYTES=279097344
EXPECTED_LBL_BYTES=1256790

mkdir -p "$RAW_DIR" "$DOWNLOAD_DIR/index" "$DOWNLOAD_DIR/evidence" "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/download.$RUN_TS.log" "$LOG_DIR/download.latest.log") 2>&1
echo "[$(date -Is)] download start dataset=$DATASET_ID data_root=$DATA_ROOT"

md5_of() { md5sum "$1" | cut -d' ' -f1; }

# fetch_small <url> <target> <size> <md5>: small pinned file, validated by size and MD5 (= S3 ETag).
fetch_small() {
  local url="$1" target="$2" size="$3" md5="$4"
  if [[ -s "$target" && "$(stat -c %s "$target")" == "$size" && "$(md5_of "$target")" == "$md5" ]]; then
    return 0
  fi
  rm -f "$target.part"
  curl --fail --silent --show-error --location --retry 10 --retry-delay 5 --retry-all-errors \
    --speed-limit 1024 --speed-time 120 --max-filesize 10000000 \
    --user-agent "$UA" --output "$target.part" "$url"
  if [[ "$(stat -c %s "$target.part")" != "$size" || "$(md5_of "$target.part")" != "$md5" ]]; then
    echo "FATAL size/MD5 mismatch for $url (expected $size / $md5)" >&2
    rm -f "$target.part"
    exit 1
  fi
  mv "$target.part" "$target"
}

# Liveness: one-byte range GET on the first pinned frame.
first_url="$(awk -F'\t' 'NR==2 {print $4}' "$SOURCES")"
curl --fail --silent --show-error --location --max-time 60 --range 0-0 \
  --user-agent "$UA" --output /dev/null "$first_url"
echo "liveness_ok url=$first_url"

# Rights/citation evidence and selection evidence (volume index), pinned by size and MD5.
fetch_small "$BASE/AAREADME.TXT" "$DOWNLOAD_DIR/evidence/AAREADME.TXT" 16978 519163f73a17285da8d6288992bc61f4
python3 "$CHECK" evidence "$DOWNLOAD_DIR/evidence/AAREADME.TXT"
fetch_small "$BASE/INDEX/INDEX.LBL" "$DOWNLOAD_DIR/index/INDEX.LBL" 12267 751cc4334b9cf5972a7df21b43a007fd
fetch_small "$BASE/INDEX/INDEX.TAB" "$DOWNLOAD_DIR/index/INDEX.TAB" 3322740 9952de72d9a6013e5e0c0ae78de50c97
python3 "$CHECK" index "$DOWNLOAD_DIR/index/INDEX.TAB" "$DOWNLOAD_DIR/index/INDEX.LBL" "$SOURCES"

plan="$DOWNLOAD_DIR/download_plan.tsv"
printf 'image_number\tproduct\timg_size\timg_md5\timg_sha256\tlbl_size\tlbl_md5\n' > "$plan.part"
count=0
img_bytes=0
lbl_bytes=0
fetched=0
while IFS='|' read -r image_number product img_url img_size img_md5 lbl_url lbl_size lbl_md5; do
  img="$RAW_DIR/${product}_RAW.IMG"
  lbl="$RAW_DIR/${product}_RAW.LBL"

  # Detached label (about 3.7 KB): size + MD5 pin, then keyword checks.
  fetch_small "$lbl_url" "$lbl" "$lbl_size" "$lbl_md5"

  # Frame (823,296 bytes): resumable, size + MD5 pin, then structural decode checks.
  digests=""
  if [[ -s "$img" ]]; then
    if [[ "$(stat -c %s "$img")" != "$img_size" ]] \
      || ! digests="$(python3 "$CHECK" frame "$img" "$lbl" "$image_number" "$product")" \
      || [[ "${digests%% *}" != "$img_md5" ]]; then
      echo "stale_or_invalid_cache product=$product; refetching"
      rm -f "$img"
      digests=""
    fi
  fi
  if [[ ! -s "$img" ]]; then
    if [[ -s "$img.part" ]] && (( $(stat -c %s "$img.part") > img_size )); then
      rm -f "$img.part"
    fi
    curl --fail --silent --show-error --location -C - \
      --retry 10 --retry-delay 5 --retry-all-errors \
      --speed-limit 1024 --speed-time 120 --max-filesize 2000000 \
      --user-agent "$UA" --output "$img.part" "$img_url"
    actual="$(stat -c %s "$img.part")"
    if [[ "$actual" != "$img_size" ]]; then
      echo "FATAL size mismatch product=$product expected=$img_size actual=$actual" >&2
      rm -f "$img.part"
      exit 1
    fi
    if ! digests="$(python3 "$CHECK" frame "$img.part" "$lbl" "$image_number" "$product")"; then
      echo "FATAL semantic validation failed product=$product" >&2
      rm -f "$img.part"
      exit 1
    fi
    if [[ "${digests%% *}" != "$img_md5" ]]; then
      echo "FATAL MD5 mismatch product=$product expected=$img_md5 actual=${digests%% *}" >&2
      rm -f "$img.part"
      exit 1
    fi
    mv "$img.part" "$img"
    fetched=$((fetched + 1))
    echo "fetched product=$product image_number=$image_number md5=$img_md5"
  fi
  printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\n' "$image_number" "$product" "$img_size" "$img_md5" "${digests##* }" \
    "$lbl_size" "$lbl_md5" >> "$plan.part"
  count=$((count + 1))
  img_bytes=$((img_bytes + img_size))
  lbl_bytes=$((lbl_bytes + lbl_size))
done < <(awk -F'\t' 'NR > 1 {print $1 "|" $2 "|" $4 "|" $5 "|" $6 "|" $8 "|" $9 "|" $10}' "$SOURCES")
mv "$plan.part" "$plan"

if [[ "$count" != "$EXPECTED_FRAMES" || "$img_bytes" != "$EXPECTED_IMG_BYTES" || "$lbl_bytes" != "$EXPECTED_LBL_BYTES" ]]; then
  echo "FATAL unexpected selection totals frames=$count img_bytes=$img_bytes lbl_bytes=$lbl_bytes" \
    "(expected $EXPECTED_FRAMES / $EXPECTED_IMG_BYTES / $EXPECTED_LBL_BYTES)" >&2
  exit 1
fi
echo "[$(date -Is)] download done dataset=$DATASET_ID frames=$count img_bytes=$img_bytes lbl_bytes=$lbl_bytes fetched_now=$fetched"
