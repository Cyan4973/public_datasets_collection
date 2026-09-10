#!/usr/bin/env bash
# Acquire only the metadata and compressed chunks needed for 3,910 events.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="zenodo_calochallenge_showers_f64"
DOWNLOAD_DIR="$REPO_ROOT/$DATA_DIR/downloads/$DATASET_ID"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
NODE_DIR="$DOWNLOAD_DIR/nodes"
RANGE_DIR="$DOWNLOAD_DIR/ranges"
URL="https://zenodo.org/api/records/6366271/files/dataset_2_1.hdf5/content"
RECORD_URL="https://zenodo.org/api/records/6366271"
TOTAL_BYTES=1356475617
PREFIX_BYTES=4194304
EVENT_COUNT=3910

mkdir -p "$DOWNLOAD_DIR" "$LOG_DIR" "$NODE_DIR" "$RANGE_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/download.$RUN_TS.log" "$LOG_DIR/download.latest.log") 2>&1
echo "[$(date -Is)] download start dataset=$DATASET_ID"

fetch_small() {
  local url="$1" output="$2" cap="$3"
  if [ -s "$output" ]; then
    echo "cache_hit file=$output bytes=$(stat -c %s "$output")"
    return
  fi
  curl --fail --silent --show-error --location \
    --retry 5 --retry-delay 3 --retry-all-errors \
    --max-time 300 --max-filesize "$cap" \
    --speed-limit 1024 --speed-time 180 \
    --user-agent "openzl-public-datasets-calochallenge-f64/1.0" \
    --output "$output.part" "$url"
  mv "$output.part" "$output"
}

fetch_range() {
  local start="$1" end="$2" output="$3"
  local expected_size=$((end - start + 1))
  local headers="$output.headers"
  if [ -s "$output" ] && [ "$(stat -c %s "$output")" = "$expected_size" ]; then
    echo "range_cache_hit start=$start end=$end bytes=$expected_size"
    return
  fi
  rm -f "$output.part" "$headers.part"
  curl --fail --silent --show-error --location \
    --retry 5 --retry-delay 3 --retry-all-errors \
    --max-time 600 --max-filesize "$((expected_size + 1))" \
    --speed-limit 1024 --speed-time 180 \
    --user-agent "openzl-public-datasets-calochallenge-f64/1.0" \
    --range "$start-$end" --dump-header "$headers.part" \
    --output "$output.part" "$URL"
  python3 - "$headers.part" "$output.part" "$start" "$end" "$TOTAL_BYTES" <<'PY'
from __future__ import annotations
import re
import sys
from pathlib import Path

headers, payload = Path(sys.argv[1]), Path(sys.argv[2])
start, end, total = map(int, sys.argv[3:])
text = headers.read_text(encoding="iso-8859-1")
found = re.findall(
    r"^Content-Range:\s*bytes\s+(\d+)-(\d+)/(\d+)\s*$",
    text,
    flags=re.IGNORECASE | re.MULTILINE,
)
if not found or tuple(map(int, found[-1])) != (start, end, total):
    raise SystemExit(f"unexpected or missing Content-Range for {start}-{end}")
if payload.stat().st_size != end - start + 1:
    raise SystemExit(f"range payload size mismatch for {start}-{end}")
PY
  mv "$headers.part" "$headers"
  mv "$output.part" "$output"
  echo "range_fetched start=$start end=$end bytes=$expected_size"
}

fetch_small "$RECORD_URL" "$DOWNLOAD_DIR/record.json" 5000000

PROBE_PREFIX="$REPO_ROOT/$DATA_DIR/discovery/$DATASET_ID/dataset_2_1.prefix"
if [ ! -s "$DOWNLOAD_DIR/prefix.bin" ] && [ -s "$PROBE_PREFIX" ] \
  && [ "$(stat -c %s "$PROBE_PREFIX")" = "$PREFIX_BYTES" ]; then
  cp "$PROBE_PREFIX" "$DOWNLOAD_DIR/prefix.bin"
  echo "reused_probe_prefix bytes=$PREFIX_BYTES"
fi
fetch_range 0 "$((PREFIX_BYTES - 1))" "$DOWNLOAD_DIR/prefix.bin"

for round in 1 2 3 4; do
  set +e
  python3 "$RECIPE_DIR/scripts/calo_hdf5.py" plan \
    --download-dir "$DOWNLOAD_DIR" --event-count "$EVENT_COUNT"
  plan_status=$?
  set -e
  if [ "$plan_status" = 0 ]; then
    break
  fi
  if [ "$plan_status" != 3 ]; then
    exit "$plan_status"
  fi
  while IFS=$'\t' read -r address length; do
    [ "$address" != "address" ] || continue
    [ -n "$address" ] || continue
    fetch_range "$address" "$((address + length - 1))" "$NODE_DIR/node_$address.bin"
  done < "$DOWNLOAD_DIR/node_requests.tsv"
done

if [ ! -s "$DOWNLOAD_DIR/chunk_plan.tsv" ] || [ ! -s "$DOWNLOAD_DIR/data_ranges.tsv" ]; then
  echo "range planning did not complete" >&2
  exit 1
fi

while IFS=$'\t' read -r range_id start end length; do
  [ "$range_id" != "range_id" ] || continue
  [ -n "$range_id" ] || continue
  fetch_range "$start" "$end" "$RANGE_DIR/$range_id.bin"
done < "$DOWNLOAD_DIR/data_ranges.tsv"

python3 "$RECIPE_DIR/scripts/calo_hdf5.py" inventory \
  --download-dir "$DOWNLOAD_DIR" --event-count "$EVENT_COUNT"

echo "[$(date -Is)] download done dataset=$DATASET_ID"
