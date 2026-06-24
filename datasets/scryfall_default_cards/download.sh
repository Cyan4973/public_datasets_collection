#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="scryfall_default_cards"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
DOWNLOAD_DIR="$REPO_ROOT/$DATA_DIR/downloads/$DATASET_ID"
mkdir -p "$LOG_DIR" "$DOWNLOAD_DIR"

RUN_TS="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="$LOG_DIR/download.$RUN_TS.log"
LATEST_LOG="$LOG_DIR/download.latest.log"
exec > >(tee "$LOG_FILE" "$LATEST_LOG") 2>&1

echo "[$(date -Is)] download start dataset=$DATASET_ID"

# Scryfall bulk data. The download URI is timestamped (changes daily), so resolve it from
# the bulk-data listing first, then fetch the chosen bulk file (default oracle_cards:
# unique cards, ~178 MB). The build extracts numeric card fields, partitioned per year.
BULK_TYPE="${SCRYFALL_BULK_TYPE:-oracle_cards}"
OUT="$DOWNLOAD_DIR/cards.json"
TMP="$OUT.tmp"
UA="openzl-public-datasets/1.0 (numeric dataset collection)"
export BULK_TYPE

# cache-hit only if the existing file is the bulk JSON array (not a stale search-dict
# from an earlier recipe version, which starts with '{')
CACHED_OK=0
if [ -s "$OUT" ] && [ "${FORCE_DOWNLOAD:-0}" != "1" ]; then
  first="$(tr -d '[:space:]' < "$OUT" | head -c1 || true)"
  [ "$first" = "[" ] && CACHED_OK=1 || echo "stale/wrong-format cache (first char='$first'); re-downloading"
fi

if [ "$CACHED_OK" = "1" ]; then
  echo "[$(date -Is)] cache_hit dataset=$DATASET_ID path=$OUT"
else
  rm -f "$OUT"   # drop any stale/wrong-format file
  echo "resolve bulk-data uri for type=$BULK_TYPE"
  URI="$(curl --globoff -fsSL --max-time 60 -A "$UA" "https://api.scryfall.com/bulk-data" \
    | python3 -c "import json,sys,os
d=json.load(sys.stdin)
t=os.environ['BULK_TYPE']
for b in d.get('data',[]):
    if b.get('type')==t:
        print(b['download_uri']); break")"
  if [ -z "$URI" ]; then
    echo "FATAL: could not resolve bulk-data uri for type=$BULK_TYPE"; exit 1
  fi
  echo "uri=$URI"
  # resumable + stall-based abort (no hard total-time cap)
  curl --globoff -fL -C - --retry 10 --retry-delay 5 \
    --speed-limit 1024 --speed-time 120 \
    -A "$UA" -o "$TMP" "$URI"
  mv "$TMP" "$OUT"
fi

# validate: JSON array whose first object has the expected numeric fields
python3 - "$OUT" <<'PY'
import json, sys
obj = json.load(open(sys.argv[1], encoding="utf-8"))
if not isinstance(obj, list) or len(obj) < 100:
    raise SystemExit(f"expected a JSON array of >=100 cards, got {type(obj).__name__}")
c = obj[0]
for k in ("cmc", "released_at"):
    if k not in c:
        raise SystemExit(f"first card missing field {k!r}: keys={list(c)[:20]}")
print(f"scryfall ok: cards={len(obj)} sample name={c.get('name')!r} cmc={c.get('cmc')} edhrec_rank={c.get('edhrec_rank')}")
PY

echo "[$(date -Is)] download done dataset=$DATASET_ID bytes=$(wc -c < "$OUT" | tr -d ' ')"
