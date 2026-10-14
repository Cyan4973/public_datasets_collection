#!/usr/bin/env bash
# Fetch the pinned WFJ_DailySMP metadata files and range-fetch only the 291
# selected S36M .PNT members out of the 3.13 GB raw_data.zip (EnviDat DOI
# 10.16904/envidat.641). Every member is checked against the archive's central
# directory and inflated with an exact size + CRC32 check.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in /*) DATA_ROOT="$DATA_DIR" ;; *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;; esac
DATASET_ID="slf_envidat_wfj_snowmicropen_force_i16"
DOWNLOAD_DIR="$DATA_ROOT/downloads/$DATASET_ID"
MEMBER_DIR="$DOWNLOAD_DIR/raw_data_members"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"
HELPER="$RECIPE_DIR/scripts/zip_members.py"
MEMBERS_TSV="$RECIPE_DIR/members.tsv"

BASE_URL="https://zhc-c.s3.cloud.switch.ch/envidat-doi/10.16904_envidat.641/data"
ZIP_URL="$BASE_URL/raw_data.zip"
ZIP_SIZE=3134603173
CD_OFFSET=3132965021
PACKAGE_URL="https://www.envidat.ch/api/action/package_show?id=wfj_dailysmp"
UA="openzl-public-datasets-envidat-wfj-smp/1.0"

mkdir -p "$DOWNLOAD_DIR" "$MEMBER_DIR" "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/download.$RUN_TS.log" "$LOG_DIR/download.latest.log") 2>&1
echo "[$(date -Is)] download start dataset=$DATASET_ID data_root=$DATA_ROOT"

CURL=(curl --globoff --fail --silent --show-error --location --retry 10 --retry-delay 5
  --retry-all-errors --connect-timeout 60 --speed-limit 1024 --speed-time 120 --user-agent "$UA")

fetch_small() {  # url target expected_size expected_md5
  local url="$1" target="$2" size="$3" md5="$4"
  if [[ -s "$target" && "$(stat -c %s "$target")" == "$size" ]] \
    && [[ "$(md5sum "$target" | awk '{print $1}')" == "$md5" ]]; then
    echo "cache_hit $(basename "$target") bytes=$size"
    return
  fi
  "${CURL[@]}" --output "$target.part" "$url"
  local actual_size actual_md5
  actual_size="$(stat -c %s "$target.part")"
  actual_md5="$(md5sum "$target.part" | awk '{print $1}')"
  if [[ "$actual_size" != "$size" || "$actual_md5" != "$md5" ]]; then
    echo "pinned file changed: $url size=$actual_size md5=$actual_md5 (expected $size $md5)" >&2
    exit 1
  fi
  mv "$target.part" "$target"
  echo "fetched $(basename "$target") bytes=$size md5=$md5"
}

# 1. Pinned small files (sizes and S3 MD5 ETags as listed 2026-10-14).
fetch_small "$BASE_URL/raw_data.csv" "$DOWNLOAD_DIR/raw_data.csv" 444663 40f11a5f364afd964e7e6e3ef65df1e5
fetch_small "$BASE_URL/LICENSE" "$DOWNLOAD_DIR/LICENSE" 1106 e240a6501986482bf61ce32ab34d95fd
fetch_small "$BASE_URL/Readme.pdf" "$DOWNLOAD_DIR/Readme.pdf" 1006460 cf7599b841ab2f5c0c5bad810b1eb6e4
grep -q "^MIT License" "$DOWNLOAD_DIR/LICENSE" || { echo "LICENSE is not the expected MIT text" >&2; exit 1; }
head -1 "$DOWNLOAD_DIR/raw_data.csv" | grep -q "^Date,File,Path,BestOfDay,Quality" \
  || { echo "raw_data.csv header changed" >&2; exit 1; }

# 2. Package metadata: the dataset license must still be CC BY-SA.
"${CURL[@]}" --max-time 120 --output "$DOWNLOAD_DIR/package_show.json.part" "$PACKAGE_URL"
mv "$DOWNLOAD_DIR/package_show.json.part" "$DOWNLOAD_DIR/package_show.json"
python3 -I - "$DOWNLOAD_DIR/package_show.json" <<'PY'
import json, sys
result = json.load(open(sys.argv[1], encoding="utf-8"))["result"]
if result.get("license_id") != "cc-by-sa" or result.get("doi") != "10.16904/envidat.641":
    sys.exit(f"package license/doi changed: {result.get('license_id')!r} {result.get('doi')!r}")
print(f"package license_id={result['license_id']} doi={result['doi']}")
PY

# 3. Archive identity and central directory (bytes CD_OFFSET..end, 1,638,152 B).
actual_zip_size="$("${CURL[@]}" --max-time 120 --head "$ZIP_URL" | tr -d '\r' \
  | awk 'tolower($1)=="content-length:" {v=$2} END {print v}')"
[[ "$actual_zip_size" == "$ZIP_SIZE" ]] || {
  echo "raw_data.zip size changed: $actual_zip_size != $ZIP_SIZE" >&2
  exit 1
}
CD_FILE="$DOWNLOAD_DIR/raw_data_zip_central_directory.bin"
if [[ ! -s "$CD_FILE" || "$(stat -c %s "$CD_FILE")" != "$((ZIP_SIZE - CD_OFFSET))" ]]; then
  "${CURL[@]}" --range "$CD_OFFSET-$((ZIP_SIZE - 1))" --output "$CD_FILE.part" "$ZIP_URL"
  mv "$CD_FILE.part" "$CD_FILE"
fi
python3 -I "$HELPER" cd-check "$CD_FILE" "$MEMBERS_TSV" "$DOWNLOAD_DIR/raw_data.csv"

# 4. Range-fetch each pinned member: local header + name + extra + deflate data.
count=0
fetched=0
member_bytes=0
while IFS=$'\t' read -r member _date _quality offset name_len extra_len csize usize crc _rest; do
  [[ "$member" != "zip_member" ]] || continue
  rel="${member#raw_data/}"
  target="$MEMBER_DIR/$rel"
  mkdir -p "$(dirname "$target")"
  count=$((count + 1))
  member_bytes=$((member_bytes + usize))
  if [[ -s "$target" ]] && python3 -I "$HELPER" crc-ok "$target" "$usize" "$crc"; then
    continue
  fi
  end=$((offset + 30 + name_len + extra_len + csize - 1))
  part="$target.range.part"
  rm -f "$part"
  "${CURL[@]}" --range "$offset-$end" --output "$part" "$ZIP_URL"
  python3 -I "$HELPER" inflate "$part" "$target" "$member" "$csize" "$usize" "$crc"
  rm -f "$part"
  fetched=$((fetched + 1))
  if (( fetched % 25 == 0 )); then
    echo "[$(date -Is)] progress members=$count fetched=$fetched"
  fi
done < "$MEMBERS_TSV"

[[ "$count" == 291 ]] || { echo "unexpected member count $count" >&2; exit 1; }
[[ "$member_bytes" == 239853056 ]] || { echo "unexpected member bytes $member_bytes" >&2; exit 1; }
on_disk="$(find "$MEMBER_DIR" -type f \( -name '*.PNT' -o -name '*.pnt' \) | wc -l)"
[[ "$on_disk" == 291 ]] || { echo "unexpected member files on disk: $on_disk" >&2; exit 1; }

echo "[$(date -Is)] download done dataset=$DATASET_ID members=$count newly_fetched=$fetched member_bytes=$member_bytes"
