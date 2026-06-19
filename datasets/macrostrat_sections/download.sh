#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="macrostrat_sections"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
DOWNLOAD_DIR="$REPO_ROOT/$DATA_DIR/downloads/$DATASET_ID"
PROBE_CACHE_FILE="$REPO_ROOT/$DATA_DIR/downloads/macrostrat_more_numeric_sources/macrostrat_sections_long.json"
mkdir -p "$LOG_DIR" "$DOWNLOAD_DIR"

RUN_TS="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="$LOG_DIR/download.$RUN_TS.log"
LATEST_LOG="$LOG_DIR/download.latest.log"
exec > >(tee "$LOG_FILE" "$LATEST_LOG") 2>&1

URL="https://macrostrat.org/api/sections?response=long"
OUT="$DOWNLOAD_DIR/macrostrat_sections.json"
FAILURES="$DOWNLOAD_DIR/download_failures.tsv"
printf 'status\tdetail\turl\n' > "$FAILURES"

echo "[$(date -Is)] download start dataset=$DATASET_ID"

if [[ -s "$OUT" && "${FORCE_DOWNLOAD:-0}" != "1" ]]; then
  echo "cache_hit path=$OUT"
elif [[ -s "$PROBE_CACHE_FILE" && "${FORCE_DOWNLOAD:-0}" != "1" ]]; then
  cp "$PROBE_CACHE_FILE" "$OUT"
  echo "seeded_from_probe_cache path=$PROBE_CACHE_FILE"
else
  rm -f "$OUT.tmp"
  if ! curl --globoff --fail --location --show-error --retry 4 --retry-delay 3 --retry-all-errors \
    --connect-timeout 30 --max-time 600 -A "openzl-public-datasets/1.0" -o "$OUT.tmp" "$URL"; then
    printf 'failed\tcurl_failed\t%s\n' "$URL" >> "$FAILURES"
    rm -f "$OUT.tmp"
    exit 1
  fi
  mv "$OUT.tmp" "$OUT"
fi

python3 - "$OUT" <<'PY'
import json
import sys

obj = json.load(open(sys.argv[1], encoding="utf-8"))
data = obj.get("success", {}).get("data")
if not isinstance(data, list) or len(data) < 10_000:
    raise SystemExit("bad Macrostrat sections payload")
required = {"t_age", "b_age", "col_area", "max_thick", "min_thick", "pbdb_collections"}
missing = sorted(required - set(data[0]))
if missing:
    raise SystemExit(f"missing expected fields: {missing}")
print(f"validated_records={len(data)} source_bytes={len(open(sys.argv[1], 'rb').read())}")
PY

echo "failure_count=0"
echo "[$(date -Is)] download done dataset=$DATASET_ID"
