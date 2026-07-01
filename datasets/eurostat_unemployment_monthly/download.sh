#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="eurostat_unemployment_monthly"
DOWNLOAD_DIR="$REPO_ROOT/$DATA_DIR/downloads/$DATASET_ID"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
mkdir -p "$DOWNLOAD_DIR" "$LOG_DIR"

RUN_TS="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="$LOG_DIR/download.$RUN_TS.log"
LATEST_LOG="$LOG_DIR/download.latest.log"
FAIL_FILE="$DOWNLOAD_DIR/download_failures.tsv"
PLAN_FILE="$DOWNLOAD_DIR/download_plan.tsv"
CHECKSUM_FILE="$DOWNLOAD_DIR/collection_checksums.sha256"
OUT="$DOWNLOAD_DIR/data.json"
TMP="$OUT.tmp"
exec > >(tee "$LOG_FILE" "$LATEST_LOG") 2>&1

echo "[$(date -Is)] download start dataset=$DATASET_ID"

BASE_URL="${EUROSTAT_UNEMPLOYMENT_URL:-https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/une_rt_m}"
MIN_VALUES="${EUROSTAT_UNEMPLOYMENT_MIN_VALUES:-100000}"

: > "$FAIL_FILE"

python3 - <<'PY' "$PLAN_FILE" "$BASE_URL"
from __future__ import annotations

import sys
import urllib.parse
from pathlib import Path

plan_path = Path(sys.argv[1])
base_url = sys.argv[2]
params = [
    ("unit", "PC_ACT"),
]
url = base_url + "?" + urllib.parse.urlencode(params)
plan_path.write_text(f"eurostat_unemployment_monthly\t{url}\tdata.json\n", encoding="utf-8")
PY

validate_payload() {
  local path="$1"
  python3 - <<'PY' "$path" "$MIN_VALUES"
from __future__ import annotations

import json
import sys
from pathlib import Path

path = Path(sys.argv[1])
min_values = int(sys.argv[2])
payload = json.loads(path.read_text(encoding="utf-8"))
if not isinstance(payload, dict):
    raise SystemExit(f"unexpected Eurostat payload shape in {path}")
if "error" in payload:
    raise SystemExit(f"Eurostat error payload in {path}")
dimension = payload.get("dimension")
if not isinstance(dimension, dict):
    raise SystemExit(f"missing dimension object in {path}")
for required in ["s_adj", "age", "sex", "geo", "time"]:
    category = (dimension.get(required) or {}).get("category") or {}
    index = category.get("index")
    if not isinstance(index, dict) or not index:
        raise SystemExit(f"missing {required} categories in {path}")
value_data = payload.get("value")
if isinstance(value_data, dict):
    value_count = len(value_data)
elif isinstance(value_data, list):
    value_count = sum(value is not None for value in value_data)
else:
    raise SystemExit(f"missing value field in {path}")
if value_count < min_values:
    raise SystemExit(f"only {value_count} sparse values < EUROSTAT_UNEMPLOYMENT_MIN_VALUES={min_values}")
print(f"semantic_validation=ok sparse_values={value_count}")
PY
}

if [ -s "$OUT" ] && [ "${FORCE_DOWNLOAD:-0}" != "1" ]; then
  if validate_payload "$OUT"; then
    echo "[$(date -Is)] cache_hit dataset=$DATASET_ID path=$OUT"
    echo "[$(date -Is)] download done dataset=$DATASET_ID"
    exit 0
  fi
  rm -f "$OUT"
fi

rm -f "$TMP"
url="$(cut -f2 "$PLAN_FILE")"
echo "fetch dataset=$DATASET_ID url=$url"
if ! curl --globoff -fL --retry 3 --retry-delay 5 -A "openzl-public-datasets/1.0" -o "$TMP" "$url"; then
  printf '%s\tcurl_failed\t%s\n' "$DATASET_ID" "$url" >> "$FAIL_FILE"
  rm -f "$TMP"
  exit 1
fi
if ! validate_payload "$TMP"; then
  printf '%s\tvalidation_failed\t%s\n' "$DATASET_ID" "$url" >> "$FAIL_FILE"
  rm -f "$TMP"
  exit 1
fi
mv "$TMP" "$OUT"
sha256sum "$OUT" > "$CHECKSUM_FILE"
echo "plan_file=$PLAN_FILE"
echo "checksum_file=$CHECKSUM_FILE"
echo "[$(date -Is)] download done dataset=$DATASET_ID"
