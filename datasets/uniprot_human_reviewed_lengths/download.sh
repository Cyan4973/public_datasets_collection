#!/usr/bin/env bash
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="uniprot_human_reviewed_lengths"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
DOWNLOAD_DIR="$REPO_ROOT/$DATA_DIR/downloads/$DATASET_ID"
mkdir -p "$LOG_DIR" "$DOWNLOAD_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="$LOG_DIR/download.$RUN_TS.log"
LATEST_LOG="$LOG_DIR/download.latest.log"
exec > >(tee "$LOG_FILE" "$LATEST_LOG") 2>&1
URL="https://rest.uniprot.org/uniprotkb/search?query=reviewed:true+AND+organism_id:9606&fields=accession,length,mass&format=tsv&size=500"
OUT="$DOWNLOAD_DIR/uniprot_human_reviewed.tsv"
TMP="$OUT.tmp"
if [ -s "$OUT" ] && [ "${FORCE_DOWNLOAD:-0}" != "1" ]; then
  echo "[$(date -Is)] cache_hit dataset=$DATASET_ID path=$OUT"
else
  rm -f "$TMP"
  curl -fL --retry 3 --retry-delay 2 -o "$TMP" "$URL"
  python3 - <<'PY' "$TMP"
import sys
first, second = open(sys.argv[1], encoding='utf-8').read().splitlines()[:2]
if "Entry" not in first or "Length" not in first or "Mass" not in first:
    raise SystemExit("bad header")
if not second:
    raise SystemExit("empty body")
PY
  mv "$TMP" "$OUT"
fi
echo "[$(date -Is)] download done dataset=$DATASET_ID"
