#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR=$(cd "$(dirname "$0")/../.." && pwd)
DATA_DIR=${DATA_DIR:-"$ROOT_DIR/.data"}
DATASET_ID=who_gho_observations
DOWNLOAD_DIR="$DATA_DIR/downloads/$DATASET_ID"
LOG_DIR="$DATA_DIR/logs/$DATASET_ID"
mkdir -p "$DOWNLOAD_DIR" "$LOG_DIR"

TS=$(date +%Y%m%d_%H%M%S)
LOG_FILE="$LOG_DIR/download.$TS.log"
LATEST_LOG="$LOG_DIR/download.latest.log"
FAIL_TSV="$DOWNLOAD_DIR/download_failures.tsv"
: > "$FAIL_TSV"
exec > >(tee "$LOG_FILE") 2>&1

log(){ printf '[%s] %s\n' "$(date --iso-8601=seconds)" "$*"; }

OUT="$DOWNLOAD_DIR/who_gho_observations.json"
if [[ "${FORCE_DOWNLOAD:-0}" != "1" && -s "$OUT" ]]; then
  log "cache_hit dataset=$DATASET_ID file=$OUT"
  cp "$LOG_FILE" "$LATEST_LOG" 2>/dev/null || true
  exit 0
fi

TMP="$DOWNLOAD_DIR/who_gho_observations.tmp"
URL="https://ghoapi.azureedge.net/api/MDG_0000000001"
log "fetch start url=$URL"
if ! curl --globoff -L --fail --retry 2 --retry-delay 2 -A 'openzl-public-datasets/1.0' -o "$TMP" "$URL"; then
  log "fetch failed reason=curl_failed"
  printf 'who_gho_observations\tcurl_failed\n' >> "$FAIL_TSV"
  rm -f "$TMP"
  cp "$LOG_FILE" "$LATEST_LOG" 2>/dev/null || true
  exit 0
fi
if ! python3 - <<'PY' "$TMP"
import json, sys
obj = json.load(open(sys.argv[1]))
assert isinstance(obj, dict) and isinstance(obj.get("value"), list)
PY
then
  log "fetch failed reason=validation_failed"
  printf 'who_gho_observations\tvalidation_failed\n' >> "$FAIL_TSV"
  rm -f "$TMP"
  cp "$LOG_FILE" "$LATEST_LOG" 2>/dev/null || true
  exit 0
fi
mv "$TMP" "$OUT"
cp "$LOG_FILE" "$LATEST_LOG" 2>/dev/null || true
log "download done failure_count=0 bytes=$(wc -c < "$OUT")"
