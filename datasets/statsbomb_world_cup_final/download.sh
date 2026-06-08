#!/usr/bin/env bash
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="statsbomb_world_cup_final"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
DOWNLOAD_DIR="$REPO_ROOT/$DATA_DIR/downloads/$DATASET_ID"
mkdir -p "$LOG_DIR" "$DOWNLOAD_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="$LOG_DIR/download.$RUN_TS.log"
LATEST_LOG="$LOG_DIR/download.latest.log"
FAIL_FILE="$DOWNLOAD_DIR/download_failures.tsv"
exec > >(tee "$LOG_FILE" "$LATEST_LOG") 2>&1
: > "$FAIL_FILE"
fetch() {
  local id="$1"; local url="$2"; local out="$3"; local key="$4"; local tmp="$out.tmp"
  if [[ "${FORCE_DOWNLOAD:-0}" != "1" && -s "$out" ]]; then
    echo "cache_hit dataset=$DATASET_ID path=$out"
    return 0
  fi
  rm -f "$tmp"
  if ! curl --globoff -fL --retry 2 --retry-delay 2 -A "openzl-public-datasets/1.0" -o "$tmp" "$url"; then
    echo -e "$id\tcurl_failed\t$url" >> "$FAIL_FILE"; rm -f "$tmp"; return 1
  fi
  python3 - <<'PY' "$tmp" "$key"
import json, sys
obj=json.load(open(sys.argv[1], encoding='utf-8'))
assert isinstance(obj, list) and len(obj) > 0
PY
  mv "$tmp" "$out"
}
fetch matches "https://raw.githubusercontent.com/statsbomb/open-data/master/data/matches/43/3.json" "$DOWNLOAD_DIR/statsbomb_matches_wc_final.json" list || true
fetch events "https://raw.githubusercontent.com/statsbomb/open-data/master/data/events/7585.json" "$DOWNLOAD_DIR/statsbomb_events_wc_final.json" list || true
failure_count="$(wc -l < "$FAIL_FILE")"
if [[ "$failure_count" != "0" ]]; then exit 1; fi
echo "[$(date -Is)] download done dataset=$DATASET_ID"
