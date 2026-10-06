#!/usr/bin/env bash
# Range-fetch 64 pinned GOOSE 3D val VLS-128 sweeps from goose_3d_val.zip.
#
# The 3.5 GB archive is never downloaded whole. The script fetches
#   1. the archive tail (LICENSE, CHANGELOG, label-mapping members, central
#      directory and end records; 316,905 bytes), validates the CC BY-SA 4.0
#      LICENSE member and that the pinned sources.tsv still matches the
#      selection re-derived from the live central directory, then
#   2. one exact byte range per pinned stored (method 0) *_vls128.bin member
#      (local header + payload), validated against the central directory
#      CRC32/size and the 16-byte point-record size, and keeps only the payload.
# Re-runs skip members whose payload already matches size and CRC32.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in /*) DATA_ROOT="$DATA_DIR" ;; *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;; esac
DATASET_ID="goose_vls128_lidar_scan_xyz_f32"
DOWNLOAD_DIR="$DATA_ROOT/downloads/$DATASET_ID"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"
SOURCES="$RECIPE_DIR/sources.tsv"
ZIPTOOL="$RECIPE_DIR/scripts/goose_zip.py"
ARCHIVE_URL="https://goose-dataset.de/storage/goose_3d_val.zip"
ARCHIVE_BYTES=3498402435
TAIL_START=3498085530
TAIL_END=3498402434
UA="openzl-public-datasets-goose-vls128/1.0"
CURL_COMMON=(--fail --silent --show-error --location --retry 10 --retry-delay 5 --retry-all-errors
  --speed-limit 1024 --speed-time 120 --user-agent "$UA")

mkdir -p "$DOWNLOAD_DIR/meta" "$DOWNLOAD_DIR/ranges" "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/download.$RUN_TS.log" "$LOG_DIR/download.latest.log") 2>&1
echo "[$(date -Is)] download start dataset=$DATASET_ID"

python3 "$ZIPTOOL" self-test

# Liveness and range support: one-byte range GET.
live_headers="$DOWNLOAD_DIR/ranges/liveness.headers"
curl "${CURL_COMMON[@]}" --max-time 120 --range 0-0 --dump-header "$live_headers" \
  --output /dev/null "$ARCHIVE_URL"
if ! grep -qiE "^content-range: bytes 0-0/$ARCHIVE_BYTES" "$live_headers"; then
  echo "FATAL: archive size changed or byte ranges unsupported" >&2
  tail -n 20 "$live_headers" >&2
  exit 1
fi
echo "liveness=ok archive_bytes=$ARCHIVE_BYTES"

# 1. Archive tail: metadata members + central directory.
tail_file="$DOWNLOAD_DIR/archive_tail.bin"
tail_headers="$DOWNLOAD_DIR/archive_tail.headers"
if [ ! -s "$tail_file" ] || [ ! -s "$tail_headers" ] || [ "${FORCE_DOWNLOAD:-0}" = "1" ]; then
  rm -f "$tail_file.part" "$tail_headers.part"
  curl "${CURL_COMMON[@]}" --max-time 600 --range "$TAIL_START-$TAIL_END" \
    --dump-header "$tail_headers.part" --output "$tail_file.part" "$ARCHIVE_URL"
  mv "$tail_headers.part" "$tail_headers"
  mv "$tail_file.part" "$tail_file"
fi
python3 "$ZIPTOOL" check-tail --tail "$tail_file" --headers "$tail_headers" \
  --sources "$SOURCES" --meta-dir "$DOWNLOAD_DIR/meta"

# 2. Pinned sweep members.
if [ "${FORCE_DOWNLOAD:-0}" = "1" ]; then
  rm -rf "$DOWNLOAD_DIR/lidar"
fi
mapfile -t todo < <(python3 "$ZIPTOOL" check-payloads --sources "$SOURCES" \
  --download-dir "$DOWNLOAD_DIR" --list)
echo "members_pinned=$(($(wc -l < "$SOURCES") - 1)) members_to_fetch=${#todo[@]}"

fetched=0
while IFS=$'\t' read -r sequence frame timestamp member offset range_start range_end payload_bytes crc32 points; do
  [ "$sequence" = "sequence" ] && continue
  need=0
  for item in "${todo[@]}"; do
    if [ "$item" = "$member" ]; then need=1; break; fi
  done
  [ "$need" = "1" ] || continue
  base="$(basename "$member")"
  out_dir="$DOWNLOAD_DIR/lidar/val/$sequence"
  out="$out_dir/$base"
  range_file="$DOWNLOAD_DIR/ranges/$base.zip-range"
  headers_file="$DOWNLOAD_DIR/ranges/$base.headers"
  mkdir -p "$out_dir"
  ok=0
  for attempt in 1 2 3; do
    rm -f "$range_file" "$headers_file" "$out.part"
    if curl "${CURL_COMMON[@]}" --range "$range_start-$range_end" \
        --max-filesize "$((range_end - range_start + 1025))" \
        --dump-header "$headers_file" --output "$range_file" "$ARCHIVE_URL" < /dev/null \
      && python3 "$ZIPTOOL" extract --sources "$SOURCES" --member "$member" \
        --range-file "$range_file" --headers "$headers_file" --out "$out.part" < /dev/null; then
      mv "$out.part" "$out"
      ok=1
      break
    fi
    echo "retry member=$base attempt=$attempt" >&2
    sleep $((attempt * 10))
  done
  rm -f "$range_file" "$headers_file"
  if [ "$ok" != "1" ]; then
    echo "FATAL: could not fetch a valid payload for $member" >&2
    exit 1
  fi
  fetched=$((fetched + 1))
  echo "fetched=$fetched/${#todo[@]} sequence=$sequence frame=$frame points=$points"
done < "$SOURCES"

python3 "$ZIPTOOL" check-payloads --sources "$SOURCES" --download-dir "$DOWNLOAD_DIR" --strict
rm -f "$live_headers"
rmdir "$DOWNLOAD_DIR/ranges" 2>/dev/null || true
du -sb "$DOWNLOAD_DIR" | awk '{print "download_bytes=" $1}'
echo "[$(date -Is)] download done dataset=$DATASET_ID"
