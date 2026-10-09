#!/usr/bin/env bash
# Fetch the Huawei Public Cloud Trace 2025 Region 5 day-30 request table
# (R5.zip, one Google Drive object) and validate it semantically.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in /*) DATA_ROOT="$DATA_DIR" ;; *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;; esac
DATASET_ID="huawei_cloud2025_serverless_request_latency_f64"
DOWNLOAD_DIR="$DATA_ROOT/downloads/$DATASET_ID"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"
mkdir -p "$DOWNLOAD_DIR" "$LOG_DIR"

RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/download.$RUN_TS.log" "$LOG_DIR/download.latest.log") 2>&1
echo "[$(date -Is)] download start dataset=$DATASET_ID"

DRIVE_ID="102AFIHkEQHuvG8-hZeWHVFqXeeI-a8xS"
URL="https://drive.usercontent.google.com/download?id=${DRIVE_ID}&export=download&confirm=t"
UA="openzl-public-datasets-huawei-cloud2025-download/1.0"
EXPECTED_SIZE=269637125
# SHA-256 of the 21,000-byte zip central directory (pins all 200 member
# names, sizes and CRC-32 values); measured by a range probe on 2026-10-09.
EXPECTED_CD_SHA256="68bd434f9a9f812826658c8b9c3150833e8871eb1cc8a7560d16bea0d9ca6a8b"
# Whole-file SHA-256, pinned from the first full fetch (2026-10-09).
EXPECTED_SHA256="5825f74443cf6e4f5df264f8c94d439fc9eae576399f9786a50ca4cb3316e60d"

TARGET="$DOWNLOAD_DIR/R5.zip"
PART="$TARGET.part"

validate() {
  python3 -I "$RECIPE_DIR/scripts/validate_zip.py" "$1" "$EXPECTED_SIZE" "$EXPECTED_CD_SHA256"
}

if [[ -f "$TARGET" ]]; then
  echo "cache_hit $TARGET bytes=$(stat -c %s "$TARGET")"
else
  # Liveness / interstitial check: a one-byte range GET must return the zip
  # magic's first byte and a non-HTML content type.
  probe_headers="$(mktemp)"
  probe_body="$(mktemp)"
  curl -fsSL --max-time 60 -A "$UA" -r 0-0 -D "$probe_headers" -o "$probe_body" "$URL"
  if grep -qi '^content-type: *text/html' "$probe_headers" || [[ "$(head -c 1 "$probe_body")" != "P" ]]; then
    echo "Drive returned an HTML interstitial or non-zip payload; refusing to download" >&2
    sed -n '1,40p' "$probe_headers" >&2
    rm -f "$probe_headers" "$probe_body"
    exit 1
  fi
  grep -i '^content-range\|^content-disposition\|^last-modified' "$probe_headers" || true
  rm -f "$probe_headers" "$probe_body"

  # Drop a partial file that does not start with the zip local-header magic
  # (e.g. a previously saved HTML page) before resuming.
  if [[ -f "$PART" ]] && [[ "$(head -c 4 "$PART" | od -An -tx1 | tr -d ' \n')" != "504b0304" ]]; then
    echo "discarding invalid partial file $PART"
    rm -f "$PART"
  fi
  if [[ -f "$PART" ]] && (( $(stat -c %s "$PART") > EXPECTED_SIZE )); then
    echo "discarding oversized partial file $PART"
    rm -f "$PART"
  fi

  echo "fetch url=$URL expected_bytes=$EXPECTED_SIZE"
  curl -fL -C - --retry 10 --retry-delay 5 --retry-all-errors \
    --speed-limit 1024 --speed-time 120 -A "$UA" -o "$PART" "$URL"
  actual="$(stat -c %s "$PART")"
  if [[ "$actual" != "$EXPECTED_SIZE" ]]; then
    echo "size mismatch: expected=$EXPECTED_SIZE actual=$actual" >&2
    exit 1
  fi
  validate "$PART"
  mv "$PART" "$TARGET"
fi

validate "$TARGET"
SHA256="$(sha256sum "$TARGET" | awk '{print $1}')"
echo "sha256=$SHA256"
if [[ -n "$EXPECTED_SHA256" && "$SHA256" != "$EXPECTED_SHA256" ]]; then
  echo "SHA-256 mismatch: expected=$EXPECTED_SHA256 actual=$SHA256" >&2
  exit 1
fi

cat > "$DOWNLOAD_DIR/download_inventory.json" <<JSON
{
  "dataset_id": "$DATASET_ID",
  "resource": "r5_request_table_zip",
  "url": "$URL",
  "local_path": "downloads/$DATASET_ID/R5.zip",
  "bytes": $(stat -c %s "$TARGET"),
  "sha256": "$SHA256",
  "central_directory_sha256": "$EXPECTED_CD_SHA256",
  "zip_members": 200
}
JSON
echo "[$(date -Is)] download done dataset=$DATASET_ID bytes=$(stat -c %s "$TARGET")"
