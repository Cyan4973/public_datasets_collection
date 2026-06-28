#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="nomis_employment"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
DOWNLOAD_DIR="$REPO_ROOT/$DATA_DIR/downloads/$DATASET_ID"
mkdir -p "$LOG_DIR" "$DOWNLOAD_DIR"

RUN_TS="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="$LOG_DIR/download.$RUN_TS.log"
LATEST_LOG="$LOG_DIR/download.latest.log"
exec > >(tee "$LOG_FILE" "$LATEST_LOG") 2>&1

echo "[$(date -Is)] download start dataset=$DATASET_ID"

BASE_URL="${NOMIS_URL:-https://www.nomisweb.co.uk/api/v01/dataset/NM_1_1.data.json}"
GEOGRAPHY="${NOMIS_GEOGRAPHY:-TYPE480}"
ITEM="${NOMIS_ITEM:-1}"
MEASURE="${NOMIS_MEASURE:-20100}"
MIN_RECORDS="${NOMIS_MIN_RECORDS:-10000}"
UA="openzl-public-datasets/1.0 (numeric dataset collection)"
OUT="$DOWNLOAD_DIR/nomis_employment.json"
INVENTORY="$DOWNLOAD_DIR/download_inventory.json"

if [ -s "$OUT" ] && [ -s "$INVENTORY" ] && [ "${FORCE_DOWNLOAD:-0}" != "1" ]; then
  python3 - <<'PY' "$INVENTORY" "$MIN_RECORDS"
import json
import sys

obj = json.load(open(sys.argv[1], encoding="utf-8"))
records = int(obj.get("record_count", 0))
if records < int(sys.argv[2]):
    raise SystemExit(1)
print(f"inventory cache_hit record_count={records} geography={obj.get('geography')}")
PY
  echo "[$(date -Is)] download done dataset=$DATASET_ID"
  exit 0
fi

TMP="$OUT.tmp"
rm -f "$TMP"
curl \
  --globoff \
  -fL \
  --get \
  --retry 3 \
  --retry-delay 2 \
  -A "$UA" \
  -o "$TMP" \
  --data-urlencode "geography=$GEOGRAPHY" \
  --data-urlencode "item=$ITEM" \
  --data-urlencode "measures=$MEASURE" \
  "$BASE_URL"

python3 - <<'PY' "$TMP" "$INVENTORY.tmp" "$BASE_URL" "$GEOGRAPHY" "$ITEM" "$MEASURE" "$MIN_RECORDS"
import json
import sys

payload_path, inventory_path, base_url, geography, item, measure, min_records = sys.argv[1:]
obj = json.load(open(payload_path, encoding="utf-8"))
obs = obj.get("obs")
if not isinstance(obs, list):
    raise SystemExit("bad NOMIS payload: missing obs list")
record_count = len(obs)
if record_count < int(min_records):
    raise SystemExit(f"only {record_count} observations < NOMIS_MIN_RECORDS={min_records}")
header = obj.get("header") or {}
if str(header.get("truncated", "false")).lower() == "true":
    raise SystemExit("NOMIS response is marked truncated")
inventory = {
    "dataset_id": "nomis_employment",
    "base_url": base_url,
    "geography": geography,
    "item": item,
    "measure": measure,
    "record_count": record_count,
    "source_bytes": len(open(payload_path, "rb").read()),
    "header_uri": header.get("uri"),
}
open(inventory_path, "w", encoding="utf-8").write(json.dumps(inventory, indent=2, sort_keys=True) + "\n")
print(f"semantic_validation=ok records={record_count} geography={geography}")
PY

mv "$TMP" "$OUT"
mv "$INVENTORY.tmp" "$INVENTORY"
echo "[$(date -Is)] download done dataset=$DATASET_ID"
