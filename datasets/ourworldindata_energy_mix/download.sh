#!/usr/bin/env bash
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="ourworldindata_energy_mix"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
DOWNLOAD_DIR="$REPO_ROOT/$DATA_DIR/downloads/$DATASET_ID"
mkdir -p "$LOG_DIR" "$DOWNLOAD_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="$LOG_DIR/download.$RUN_TS.log"
LATEST_LOG="$LOG_DIR/download.latest.log"
exec > >(tee "$LOG_FILE" "$LATEST_LOG") 2>&1
OUT="$DOWNLOAD_DIR/ourworldindata_energy_mix.csv"
TMP="$OUT.tmp"
URL="https://ourworldindata.org/grapher/sub-energy-fossil-renewables-nuclear.csv?v=1&csvType=full&useColumnShortNames=false"
if [ -s "$OUT" ] && [ "${FORCE_DOWNLOAD:-0}" != "1" ]; then
  echo "[$(date -Is)] cache_hit dataset=$DATASET_ID path=$OUT"
else
  rm -f "$TMP"
  curl --globoff -fL --retry 3 --retry-delay 2 -A "openzl-public-datasets/1.0" -o "$TMP" "$URL"
  python3 - <<'PY' "$TMP"
import csv, sys
with open(sys.argv[1], encoding='utf-8', newline='') as f:
    r=csv.DictReader(f)
    fields=r.fieldnames or []
    if not {'Entity','Code','Year','Nuclear','Renewables','Fossil fuels'}.issubset(fields):
        raise SystemExit('bad ourworldindata_energy_mix payload')
PY
  mv "$TMP" "$OUT"
fi
echo "[$(date -Is)] download done dataset=$DATASET_ID"
