#!/usr/bin/env bash
# Fetch the 24 pinned Klein side-scan XTF members of the USGS 2015-315-FA
# Grand Bay data release by exact ZIP byte range (never the 9.84 GB archive),
# validate each against the archive's central directory, and inflate them.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in /*) DATA_ROOT="$DATA_DIR" ;; *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;; esac
DATASET_ID="usgs_grandbay_klein3900_sidescan_xtf_u16"
DOWNLOAD_DIR="$DATA_ROOT/downloads/$DATASET_ID"
XTF_DIR="$DOWNLOAD_DIR/xtf"
PART_DIR="$DOWNLOAD_DIR/ranges"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"
HELPER="$RECIPE_DIR/scripts/xtf_sidescan.py"
SOURCES="$RECIPE_DIR/sources.tsv"

ARCHIVE_URL="https://coastal.er.usgs.gov/data-release/doi-P9374DKQ/data/2015-315-FA_xtf.zip"
ARCHIVE_BYTES=9843630446
TAIL_START=9843564910   # last 65,536 bytes: ZIP64 EOCD + 11,976-byte central directory
METADATA_URL="https://coastal.er.usgs.gov/data-release/doi-P9374DKQ/data/GrandBay_2015-315-FA_metadata.txt"
METADATA_SHA256="36736ed67024c1130c5ec8affef67c9d9756e44a0eb67d530a32480d5897f770"
UA="openzl-public-datasets-usgs-grandbay-sidescan/1.0"
MAX_ATTEMPTS="${MAX_ATTEMPTS:-12}"

mkdir -p "$DOWNLOAD_DIR" "$XTF_DIR" "$PART_DIR" "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/download.$RUN_TS.log" "$LOG_DIR/download.latest.log") 2>&1
echo "[$(date -Is)] download start dataset=$DATASET_ID data_root=$DATA_ROOT"

small_get() {  # url output max_bytes
  rm -f "$2.part"
  curl --fail --silent --show-error --location --retry 5 --retry-delay 5 --retry-all-errors \
    --connect-timeout 30 --max-time 300 --max-filesize "$3" --user-agent "$UA" \
    --output "$2.part" "$1"
  mv "$2.part" "$2"
}

# 1. License / provenance: the FGDC metadata must still carry the public-domain constraints.
metadata="$DOWNLOAD_DIR/GrandBay_2015-315-FA_metadata.txt"
if [ ! -s "$metadata" ] || [ "${FORCE_DOWNLOAD:-0}" = "1" ]; then
  small_get "$METADATA_URL" "$metadata" 1000000
fi
python3 "$HELPER" check-metadata "$metadata" "$METADATA_SHA256"

# 2. Archive identity: total size from Content-Range, central-directory SHA-256, and
#    every pinned member's offset/size/CRC32 must match sources.tsv.
tail_file="$DOWNLOAD_DIR/archive_tail.bin"
tail_headers="$DOWNLOAD_DIR/archive_tail.headers"
rm -f "$tail_file.part" "$tail_headers.part"
curl --fail --silent --show-error --location --retry 5 --retry-delay 5 --retry-all-errors \
  --connect-timeout 30 --max-time 300 --max-filesize 70000 --user-agent "$UA" \
  --range "$TAIL_START-$((ARCHIVE_BYTES - 1))" \
  --dump-header "$tail_headers.part" --output "$tail_file.part" "$ARCHIVE_URL"
mv "$tail_headers.part" "$tail_headers"
mv "$tail_file.part" "$tail_file"
python3 "$HELPER" check-cd "$tail_file" "$tail_headers" "$SOURCES"

# 3. Resumable exact-range fetch. `curl --range` cannot be combined with
#    `--continue-at -` (curl then requests from the resume offset to EOF of the
#    whole archive), so resume is done here: each attempt requests
#    [start + bytes_already_held, end] into a chunk file, the chunk's 206
#    Content-Range is validated, and the chunk is appended. --max-filesize
#    refuses any response larger than the bytes still needed (e.g. a 200 with
#    the full 9.84 GB body).
fetch_range() {  # start end dest
  local start="$1" end="$2" dest="$3"
  local want=$((end - start + 1)) have from chunk_bytes attempt rc
  local chunk="$dest.chunk" headers="$dest.chunk.headers"
  for attempt in $(seq 1 "$MAX_ATTEMPTS"); do
    have=0
    [ -f "$dest" ] && have="$(stat -c %s "$dest")"
    if [ "$have" -eq "$want" ]; then
      return 0
    fi
    if [ "$have" -gt "$want" ]; then
      echo "discarding oversized partial $dest ($have > $want)"
      rm -f "$dest"
      have=0
    fi
    from=$((start + have))
    rm -f "$chunk" "$headers"
    rc=0
    curl --fail --silent --show-error --location --connect-timeout 30 \
      --speed-limit 1024 --speed-time 120 --max-filesize "$((want - have))" \
      --user-agent "$UA" --range "$from-$end" \
      --dump-header "$headers" --output "$chunk" "$ARCHIVE_URL" || rc=$?
    if [ -s "$chunk" ] && [ -s "$headers" ]; then
      chunk_bytes="$(stat -c %s "$chunk")"
      if python3 "$HELPER" check-range "$headers" "$from" "$end" "$chunk_bytes"; then
        cat "$chunk" >> "$dest"
      else
        echo "rejected chunk for $dest (attempt $attempt)"
      fi
    fi
    rm -f "$chunk" "$headers"
    have=0
    [ -f "$dest" ] && have="$(stat -c %s "$dest")"
    if [ "$have" -eq "$want" ]; then
      return 0
    fi
    echo "attempt $attempt for $(basename "$dest"): curl rc=$rc have=$have/$want; retrying"
    sleep $((attempt < 6 ? attempt * 5 : 30))
  done
  echo "FATAL: could not fetch $(basename "$dest") after $MAX_ATTEMPTS attempts" >&2
  return 1
}

# 4. Per member: reuse a validated extracted file, else range-fetch, validate the
#    local header and DEFLATE stream (size + CRC32 from the central directory),
#    check the XTF file header, and drop the compressed range.
fetched=0
reused=0
while IFS=$'\t' read -r -u 3 member lho range_end csz usz crc pings date; do
  [ "$member" = "member" ] && continue
  out="$XTF_DIR/$member"
  if [ -s "$out" ] && [ "${FORCE_DOWNLOAD:-0}" != "1" ]; then
    if python3 "$HELPER" check-xtf "$out" "$usz" "$crc"; then
      reused=$((reused + 1))
      continue
    fi
    echo "cached $member failed validation; refetching"
    rm -f "$out"
  fi
  range_file="$PART_DIR/$member.zip-range"
  [ "${FORCE_DOWNLOAD:-0}" = "1" ] && rm -f "$range_file"
  echo "[$(date -Is)] fetch $member bytes=$lho-$range_end ($((range_end - lho + 1)) B) pings=$pings date=$date"
  fetch_range "$lho" "$range_end" "$range_file"
  if ! python3 "$HELPER" extract "$range_file" "$out.part" "$member" "$lho" "$range_end" "$csz" "$usz" "$crc"; then
    echo "member $member failed ZIP/DEFLATE validation; removing range so a re-run refetches it" >&2
    rm -f "$range_file" "$out.part"
    exit 1
  fi
  mv "$out.part" "$out"
  python3 "$HELPER" check-xtf "$out" "$usz" "$crc"
  rm -f "$range_file"
  fetched=$((fetched + 1))
done 3< "$SOURCES"

expected_members="$(($(wc -l < "$SOURCES") - 1))"
present="$(find "$XTF_DIR" -maxdepth 1 -name '*.xtf' -type f | wc -l)"
if [ "$present" -ne "$expected_members" ]; then
  echo "FATAL: $present extracted members present, expected $expected_members" >&2
  exit 1
fi
rmdir "$PART_DIR" 2>/dev/null || true
echo "[$(date -Is)] download done dataset=$DATASET_ID fetched=$fetched reused=$reused members=$present bytes_on_disk=$(du -sb "$DOWNLOAD_DIR" | cut -f1)"
