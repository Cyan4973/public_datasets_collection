#!/usr/bin/env bash
# Fetch the pinned FFIEC/CFPB HMDA 2023 snapshot national public LAR zip and
# validate it semantically (single zip64 member, exact size, CRC-32 over the
# whole decompressed CSV, pinned 99-column header).
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in /*) DATA_ROOT="$DATA_DIR" ;; *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;; esac
DATASET_ID="cfpb_hmda2023_lar_closing_costs_f64"
URL="https://files.ffiec.cfpb.gov/static-data/snapshot/2023/2023_public_lar_csv.zip"
EXPECTED_BYTES=624535331
# SHA-256 of the zip, pinned from the first full download 2026-10-09 (the
# member CRC-32, size and header hash are pinned in scripts/hmda_costs.py).
EXPECTED_SHA256="${EXPECTED_SHA256:-addc78ab14d89ba5ea3169386c514421459f2d59978885c6dbdf54d2a567b19a}"
DOWNLOAD_DIR="$DATA_ROOT/downloads/$DATASET_ID"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"
# No --user-agent override: the files.ffiec.cfpb.gov WAF answers 403 to custom
# and browser-like UAs (observed 2026-10-09) but serves curl's default UA.

mkdir -p "$DOWNLOAD_DIR" "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/download.$RUN_TS.log" "$LOG_DIR/download.latest.log") 2>&1
echo "[$(date -Is)] download start dataset=$DATASET_ID"

archive="$DOWNLOAD_DIR/2023_public_lar_csv.zip"
if [ -s "$archive" ] && [ "$(wc -c < "$archive" | tr -d ' ')" = "$EXPECTED_BYTES" ] && [ "${FORCE_DOWNLOAD:-0}" != "1" ]; then
  echo "cache_hit path=$archive"
else
  if [ "${FORCE_DOWNLOAD:-0}" = "1" ]; then rm -f "$archive" "$archive.part"; fi
  if [ -s "$archive" ]; then mv "$archive" "$archive.part"; fi
  # Liveness: one-byte range GET.
  curl --fail --silent --show-error --location --max-time 60 --range 0-0 \
    --output /dev/null "$URL"
  echo "downloading url=$URL expected_bytes=$EXPECTED_BYTES"
  curl --fail --location --continue-at - \
    --retry 10 --retry-delay 5 --retry-all-errors \
    --speed-limit 1024 --speed-time 120 \
    --output "$archive.part" "$URL"
  mv "$archive.part" "$archive"
fi

actual_bytes="$(wc -c < "$archive" | tr -d ' ')"
if [ "$actual_bytes" != "$EXPECTED_BYTES" ]; then
  echo "FATAL: zip size mismatch expected=$EXPECTED_BYTES actual=$actual_bytes" >&2
  exit 1
fi
actual_sha256="$(sha256sum "$archive" | cut -d' ' -f1)"
echo "zip_sha256=$actual_sha256"
if [ -n "$EXPECTED_SHA256" ] && [ "$actual_sha256" != "$EXPECTED_SHA256" ]; then
  echo "FATAL: zip SHA-256 mismatch expected=$EXPECTED_SHA256" >&2
  exit 1
fi

python3 -I "$RECIPE_DIR/scripts/hmda_costs.py" validate --archive "$archive"

echo "[$(date -Is)] download done dataset=$DATASET_ID bytes=$actual_bytes"
