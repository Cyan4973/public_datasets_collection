#!/usr/bin/env bash
# Fetch the pinned subset of the Egyptian fruit bat vocalization recordings
# (Prat et al. 2017, figshare collection 3666502, CC0) by HTTP range requests:
#   1. figshare API article JSON for the 30 archive articles and FileInfo.csv
#      (license and file identity check),
#   2. the last 1,024 bytes (EOCD / ZIP64 EOCD) and the central directory of
#      each of the 30 ZIP archives (30.5 MB in total, sha256-pinned),
#   3. FileInfo.csv (31.6 MB, md5 + sha256 pinned),
#   4. the 400 member spans pinned in members.tsv (local header + LZMA data,
#      131.3 MB in total), each validated by a full LZMA decode, CRC32 against
#      the central directory, and a RIFF/WAVE PCM 1 ch 250 kHz 16-bit check.
# The 98 GB of archives are never downloaded whole.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in /*) DATA_ROOT="$DATA_DIR" ;; *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;; esac
DATASET_ID="figshare_rousettus_vocalizations_i16"
DOWNLOAD_DIR="$DATA_ROOT/downloads/$DATASET_ID"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"
UA="openzl-public-datasets-rousettus/1.0"
PY=(python3 "$RECIPE_DIR/scripts/rousettus.py")
MAX_PASSES="${ROUSETTUS_MAX_PASSES:-8}"
PARALLEL="${ROUSETTUS_PARALLEL:-4}"
API="https://api.figshare.com/v2/articles"
NDL="https://ndownloader.figshare.com/files"
TAIL_BYTES=1024

FILEINFO_ARTICLE=4555897
FILEINFO_FILE=8900695
FILEINFO_SIZE=31574701
FILEINFO_MD5="b27252490ac5618bd55a9038110809d5"
FILEINFO_SHA256="753529d166f8cbb6f900fa54d3d5122d1e47bae5d6be59669e37f33e4cc1ed34"

mkdir -p "$DOWNLOAD_DIR/api" "$DOWNLOAD_DIR/zip_tails" "$DOWNLOAD_DIR/central_directories" "$DOWNLOAD_DIR/members" "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/download.$RUN_TS.log" "$LOG_DIR/download.latest.log") 2>&1
echo "[$(date -Is)] download start dataset=$DATASET_ID dir=$DOWNLOAD_DIR"

size_of() {
  if [ -f "$1" ]; then wc -c < "$1" | tr -d ' '; else echo 0; fi
}

curl_common=(--fail --silent --show-error --location --retry 10 --retry-delay 5 --retry-all-errors
  --connect-timeout 30 --speed-limit 1024 --speed-time 120 --user-agent "$UA")

# Small API JSON (article metadata incl. license); bounded size.
fetch_api() {
  local article_id="$1" out="$DOWNLOAD_DIR/api/article_$1.json"
  if [ -s "$out" ]; then
    return
  fi
  curl "${curl_common[@]}" --max-filesize 2000000 --output "$out.part" "$API/$article_id"
  mv "$out.part" "$out"
}

# Exact byte range of an archive through ndownloader (fresh presigned URL per
# call); the result must have exactly the requested length.
fetch_range() {
  local file_id="$1" first="$2" last="$3" out="$4"
  local length=$((last - first + 1))
  if [ "$(size_of "$out")" = "$length" ]; then
    return
  fi
  rm -f "$out" "$out.part"
  curl "${curl_common[@]}" --max-filesize $((length + 4096)) --range "$first-$last" \
    --output "$out.part" "$NDL/$file_id"
  if [ "$(size_of "$out.part")" != "$length" ]; then
    echo "FATAL: range $first-$last of figshare file $file_id returned $(size_of "$out.part") bytes, expected $length" >&2
    rm -f "$out.part"
    exit 1
  fi
  mv "$out.part" "$out"
}

# 1. article metadata (license + pinned file identity are checked below).
echo "[$(date -Is)] step=api_metadata"
while read -r archive article_id file_id size cd_offset cd_size; do
  fetch_api "$article_id"
done < <("${PY[@]}" archive-list)
fetch_api "$FILEINFO_ARTICLE"

# 2. archive tails (EOCD, ZIP64 EOCD) and central directories.
echo "[$(date -Is)] step=zip_listings"
while read -r archive article_id file_id size cd_offset cd_size; do
  fetch_range "$file_id" $((size - TAIL_BYTES)) $((size - 1)) "$DOWNLOAD_DIR/zip_tails/$archive.tail"
  fetch_range "$file_id" "$cd_offset" $((cd_offset + cd_size - 1)) "$DOWNLOAD_DIR/central_directories/$archive.cd"
done < <("${PY[@]}" archive-list)

# 3. FileInfo.csv (treatment, channel and recording time per file); resumable.
echo "[$(date -Is)] step=fileinfo"
FILEINFO="$DOWNLOAD_DIR/FileInfo.csv"
if ! { [ -s "$FILEINFO" ] && printf '%s  %s\n' "$FILEINFO_SHA256" "$FILEINFO" | sha256sum --check --status; }; then
  rm -f "$FILEINFO"
  if [ "$(size_of "$FILEINFO.part")" -gt "$FILEINFO_SIZE" ]; then
    rm -f "$FILEINFO.part"
  fi
  if [ "$(size_of "$FILEINFO.part")" != "$FILEINFO_SIZE" ]; then
    curl "${curl_common[@]}" --continue-at - --max-filesize $((FILEINFO_SIZE + 4096)) \
      --output "$FILEINFO.part" "$NDL/$FILEINFO_FILE"
  fi
  if ! printf '%s  %s\n' "$FILEINFO_MD5" "$FILEINFO.part" | md5sum --check --status \
    || ! printf '%s  %s\n' "$FILEINFO_SHA256" "$FILEINFO.part" | sha256sum --check --status; then
    echo "FATAL: FileInfo.csv checksum mismatch (upstream changed or transfer corrupted)" >&2
    rm -f "$FILEINFO.part"
    exit 1
  fi
  mv "$FILEINFO.part" "$FILEINFO"
fi

# License (CC0) and file identity from the API, EOCDs, central-directory
# sha256, FileInfo.csv, and a re-derivation of the member selection, which
# must reproduce members.tsv exactly.
"${PY[@]}" check-metadata --download-dir "$DOWNLOAD_DIR"
echo "[$(date -Is)] metadata_ok license=CC0 archives=30"

# 4. member spans: several passes; each pass promotes validated .part files,
#    deletes invalid ones, and refetches whatever is still missing.
export ROUSETTUS_DOWNLOAD_DIR="$DOWNLOAD_DIR" ROUSETTUS_UA="$UA"
PLAN="$DOWNLOAD_DIR/.member_plan.txt"
PENDING_FILE="$DOWNLOAD_DIR/.member_pending"
pass=0
while :; do
  "${PY[@]}" check-members --download-dir "$DOWNLOAD_DIR"
  "${PY[@]}" plan-members --download-dir "$DOWNLOAD_DIR" --plan "$PLAN" --pending-out "$PENDING_FILE"
  pending="$(cat "$PENDING_FILE")"
  if [ "$pending" = "0" ]; then
    break
  fi
  pass=$((pass + 1))
  if [ "$pass" -gt "$MAX_PASSES" ]; then
    echo "FATAL: $pending member spans still missing or invalid after $MAX_PASSES passes" >&2
    exit 1
  fi
  echo "[$(date -Is)] member fetch pass=$pass pending=$pending parallel=$PARALLEL"
  xargs -r -P "$PARALLEL" -L 1 bash "$RECIPE_DIR/scripts/fetch_span.sh" < "$PLAN"
done
rm -f "$PLAN" "$PENDING_FILE"

"${PY[@]}" check-downloads --download-dir "$DOWNLOAD_DIR"
echo "[$(date -Is)] download done dataset=$DATASET_ID bytes=$(du -sb "$DOWNLOAD_DIR" | cut -f1)"
