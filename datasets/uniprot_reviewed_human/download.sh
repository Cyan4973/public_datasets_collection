#!/usr/bin/env bash
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="uniprot_reviewed_human"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
DOWNLOAD_DIR="$REPO_ROOT/$DATA_DIR/downloads/$DATASET_ID"
mkdir -p "$LOG_DIR" "$DOWNLOAD_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="$LOG_DIR/download.$RUN_TS.log"
LATEST_LOG="$LOG_DIR/download.latest.log"
exec > >(tee "$LOG_FILE" "$LATEST_LOG") 2>&1
OUT="$DOWNLOAD_DIR/uniprot_reviewed_human.json"
URL="https://rest.uniprot.org/uniprotkb/search?query=(reviewed:true)%20AND%20(organism_id:9606)&format=json&size=500&fields=accession,length,mass"
if [[ -f "$OUT" && "${FORCE_DOWNLOAD:-0}" != "1" ]]; then
  echo "[$(date -Is)] cache_hit dataset=$DATASET_ID path=$OUT"
  exit 0
fi
TMP="$OUT.tmp"
curl --globoff -L --fail --retry 2 --retry-delay 2 -A 'openzl-public-datasets/1.0' -o "$TMP" "$URL"
python3 - <<'PY' "$TMP"
import json, sys
obj=json.load(open(sys.argv[1],encoding='utf-8'))
seq=obj.get('results') or obj.get('entries') or []
assert isinstance(seq,list) and len(seq)>0
PY
mv "$TMP" "$OUT"
echo "[$(date -Is)] download done dataset=$DATASET_ID path=$OUT bytes=$(wc -c < "$OUT")"
