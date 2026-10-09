#!/usr/bin/env bash
# Fetch the 13 pinned left-wrist GENEActiv .bin members of the Newcastle
# PSG+Accelerometer study 2015 (Zenodo record 1160410, CC BY 4.0) by exact ZIP
# byte range (194,859,344 bytes), never the whole 962,798,652-byte ZIP:
#   1. Zenodo record JSON: license cc-by-4.0, open access, DOI, ZIP size + md5;
#   2. the ZIP central directory + EOCD (last 10,396 bytes), which must
#      re-derive members.tsv exactly (selection rule, offsets, CRC32, sizes);
#   3. each member span [local header, next local header), resumed by manual
#      offset, then inflated in full and checked: CRC32, size, GENEActiv page
#      structure (85.7 Hz, -8 to 8 g, 300 samples/page, page count = header).
# participants_info.csv and the PSG .txt files are never requested. No header
# value of the GENEActiv files is printed or logged.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in /*) DATA_ROOT="$DATA_DIR" ;; *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;; esac
DATASET_ID="zenodo_newcastle_geneactiv_wrist_accel_i16"
DOWNLOAD_DIR="$DATA_ROOT/downloads/$DATASET_ID"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"
MEMBERS="$RECIPE_DIR/members.tsv"
PY=(python3 -I "$RECIPE_DIR/scripts/geneactiv.py")
RECORD_URL="https://zenodo.org/api/records/1160410"
ZIP_URL="https://zenodo.org/api/records/1160410/files/dataset_psgnewcastle2015_v1.0.zip/content"
ZIP_SIZE=962798652
CD_OFFSET=962788256
UA="openzl-public-datasets-geneactiv/1.0"
MAX_ATTEMPTS=40
EXPECTED_MEMBERS=13

mkdir -p "$DOWNLOAD_DIR/members" "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/download.$RUN_TS.log" "$LOG_DIR/download.latest.log") 2>&1
echo "[$(date -Is)] download start dataset=$DATASET_ID data_root=$DATA_ROOT"

# validate_headers <header_file> <from> <to>: final response must be 206 with
# exactly the requested Content-Range (proxy CONNECT / redirect blocks skipped).
validate_headers() {
  python3 -I - "$1" "$2" "$3" "$ZIP_SIZE" <<'PY'
import re, sys
text = open(sys.argv[1], encoding="iso-8859-1").read()
start, end, total = int(sys.argv[2]), int(sys.argv[3]), int(sys.argv[4])
blocks = [b for b in re.split(r"(?=^HTTP/)", text, flags=re.M) if b.strip()]
final = blocks[-1] if blocks else ""
status = re.search(r"^HTTP/\S+\s+(\d+)", final, flags=re.M)
crange = re.search(r"^content-range:\s*bytes\s+(\d+)-(\d+)/(\d+)", final, flags=re.M | re.I)
if not status or status.group(1) != "206" or not crange:
    raise SystemExit(f"range request not honored (status={status.group(1) if status else None})")
if tuple(map(int, crange.groups())) != (start, end, total):
    raise SystemExit(f"unexpected Content-Range {crange.groups()} for {start}-{end}/{total}")
PY
}

# fetch_range <start> <end> <out>: resumable exact byte range of the ZIP.
fetch_range() {
  local start="$1" end="$2" out="$3"
  local total=$((end - start + 1)) attempt=0 have from got
  while :; do
    have=0
    [ -f "$out.part" ] && have="$(stat -c %s "$out.part")"
    if [ "$have" -eq "$total" ]; then break; fi
    if [ "$have" -gt "$total" ]; then echo "oversized partial $out.part; restarting"; rm -f "$out.part"; continue; fi
    attempt=$((attempt + 1))
    if [ "$attempt" -gt "$MAX_ATTEMPTS" ]; then
      echo "FATAL: range $start-$end incomplete after $MAX_ATTEMPTS attempts" >&2
      exit 1
    fi
    from=$((start + have))
    rm -f "$out.chunk" "$out.hdr"
    if ! curl --fail --silent --show-error --location --connect-timeout 60 \
        --speed-limit 1024 --speed-time 120 --max-filesize $((end - from + 1 + 4096)) \
        --range "$from-$end" --user-agent "$UA" \
        --dump-header "$out.hdr" --output "$out.chunk" "$ZIP_URL" < /dev/null; then
      echo "curl interrupted at offset $from (attempt $attempt); resuming"
    fi
    if [ -s "$out.chunk" ]; then
      validate_headers "$out.hdr" "$from" "$end"
      got="$(stat -c %s "$out.chunk")"
      if [ $((have + got)) -gt "$total" ]; then
        echo "FATAL: server sent more bytes than requested for $out" >&2
        exit 1
      fi
      cat "$out.chunk" >> "$out.part"
    else
      sleep $((attempt < 6 ? 5 * attempt : 30))
    fi
    rm -f "$out.chunk"
  done
  rm -f "$out.hdr"
  mv "$out.part" "$out"
}

# 1. record metadata (license, DOI, file identity)
rec="$DOWNLOAD_DIR/zenodo_record_1160410.json"
rm -f "$rec.part"
curl --fail --silent --show-error --location --retry 5 --retry-delay 5 --retry-all-errors \
  --max-time 120 --max-filesize 2000000 --user-agent "$UA" --output "$rec.part" "$RECORD_URL"
mv "$rec.part" "$rec"
"${PY[@]}" check-record "$rec"

# 2. central directory + EOCD (always re-read; 10,396 bytes)
tail_file="$DOWNLOAD_DIR/zip_central_directory.bin"
rm -f "$tail_file" "$tail_file.part"
fetch_range "$CD_OFFSET" $((ZIP_SIZE - 1)) "$tail_file"
"${PY[@]}" check-cd "$tail_file" "$MEMBERS"

# 3. member spans
n_done=0
while IFS=$'\t' read -r sid member crc csize usize rstart rend; do
  out="$DOWNLOAD_DIR/members/$sid.zipspan"
  want=$((rend - rstart + 1))
  if [ -f "$out" ] && [ "$(stat -c %s "$out")" -eq "$want" ] && \
      "${PY[@]}" check-span "$out" "$MEMBERS" "$sid" < /dev/null; then
    echo "cache_hit sample=$sid"
  else
    rm -f "$out"
    echo "[$(date -Is)] fetching sample=$sid bytes=$want"
    fetch_range "$rstart" "$rend" "$out.fetched"
    if ! "${PY[@]}" check-span "$out.fetched" "$MEMBERS" "$sid" < /dev/null; then
      echo "FATAL: $sid span failed validation; removed" >&2
      rm -f "$out.fetched"
      exit 1
    fi
    mv "$out.fetched" "$out"
  fi
  n_done=$((n_done + 1))
done < <(grep -v '^#' "$MEMBERS" | tail -n +2)

if [ "$n_done" -ne "$EXPECTED_MEMBERS" ]; then
  echo "FATAL: expected $EXPECTED_MEMBERS pinned members, processed $n_done" >&2
  exit 1
fi
echo "[$(date -Is)] download done dataset=$DATASET_ID members=$n_done bytes=$(du -sb "$DOWNLOAD_DIR" | cut -f1)"
