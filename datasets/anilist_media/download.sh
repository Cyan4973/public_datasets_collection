#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="anilist_media"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
DOWNLOAD_DIR="$REPO_ROOT/$DATA_DIR/downloads/$DATASET_ID"
PAGES_DIR="$DOWNLOAD_DIR/pages"
mkdir -p "$LOG_DIR" "$DOWNLOAD_DIR" "$PAGES_DIR"

RUN_TS="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="$LOG_DIR/download.$RUN_TS.log"
LATEST_LOG="$LOG_DIR/download.latest.log"
exec > >(tee "$LOG_FILE" "$LATEST_LOG") 2>&1

echo "[$(date -Is)] download start dataset=$DATASET_ID"

# Shard by START-DATE year (captures all formats, not just seasonal TV like seasonYear does),
# each year well under AniList's ~5000-result pagination cap. Capped at MAX_PAGES_PER_YEAR
# (we only need >= ~1000/year). Paced for the strict rate limit. Partition = filename year.
API="https://graphql.anilist.co"
MEDIA_TYPE="${ANILIST_TYPE:-ANIME}"
START_YEAR="${ANILIST_START_YEAR:-2005}"
END_YEAR="${ANILIST_END_YEAR:-2025}"
MAX_PAGES_PER_YEAR="${ANILIST_MAX_PAGES_PER_YEAR:-30}"
SLEEP="${ANILIST_SLEEP:-1.5}"
UA="openzl-public-datasets/1.0 (numeric dataset collection)"
QUERY='query($p:Int,$t:MediaType,$gt:FuzzyDateInt,$lt:FuzzyDateInt){Page(page:$p,perPage:50){pageInfo{hasNextPage}media(type:$t,startDate_greater:$gt,startDate_lesser:$lt,sort:ID){averageScore popularity favourites episodes duration}}}'
export QUERY

fetch_page() {  # year page outfile -> echoes "hasNextPage media_count"
  local y="$1" p="$2" out="$3" body gt lt
  gt=$(( y * 10000 - 1 ))         # startDate >  (Y-1)9999  -> includes year-only Y0000
  lt=$(( (y + 1) * 10000 ))       # startDate <  (Y+1)0000
  body="$(GT="$gt" LT="$lt" P="$p" T="$MEDIA_TYPE" python3 -c 'import json,os; print(json.dumps({"query":os.environ["QUERY"],"variables":{"p":int(os.environ["P"]),"t":os.environ["T"],"gt":int(os.environ["GT"]),"lt":int(os.environ["LT"])}}))')"
  curl --globoff -fsSL --retry 8 --retry-delay 8 --retry-all-errors \
    --speed-limit 1 --speed-time 60 \
    -A "$UA" -H "Content-Type: application/json" -H "Accept: application/json" \
    --data "$body" -o "$out" "$API"
  python3 - "$out" <<'PY'
import json, sys
try:
    pg = json.load(open(sys.argv[1], encoding="utf-8"))["data"]["Page"]
    print(f"{1 if pg['pageInfo']['hasNextPage'] else 0} {len(pg['media'])}")
except Exception as e:
    print(f"PARSE_ERROR {e}", file=sys.stderr); sys.exit(3)
PY
}

# fail-fast on a recent year
PROBE="$PAGES_DIR/year_${END_YEAR}_p001.json"
if [ ! -s "$PROBE" ]; then
  echo "probe year=$END_YEAR page=1"
  if ! read -r hasnext n < <(fetch_page "$END_YEAR" 1 "$PROBE"); then
    echo "FATAL: first AniList request failed."; rm -f "$PROBE"; exit 1
  fi
  [ "${n:-0}" -le 0 ] && { echo "FATAL: probe returned 0 media."; rm -f "$PROBE"; exit 1; }
  echo "probe ok media=$n hasNextPage=$hasnext"
  sleep "$SLEEP"
fi

pages_fetched=0
for y in $(seq "$START_YEAR" "$END_YEAR"); do
  p=1
  while [ "$p" -le "$MAX_PAGES_PER_YEAR" ]; do
    out="$(printf '%s/year_%04d_p%03d.json' "$PAGES_DIR" "$y" "$p")"
    if [ -s "$out" ]; then
      hasnext="$(python3 -c "import json,sys;print(1 if json.load(open(sys.argv[1]))['data']['Page']['pageInfo']['hasNextPage'] else 0)" "$out" 2>/dev/null || echo 0)"
    else
      if ! read -r hasnext n < <(fetch_page "$y" "$p" "$out"); then
        echo "WARN: fetch failed year=$y page=$p (skipping rest of year)"; rm -f "$out"; break
      fi
      pages_fetched=$((pages_fetched + 1))
      [ "$p" -eq 1 ] && echo "year=$y page1_media=$n"
      sleep "$SLEEP"
    fi
    [ "${hasnext:-0}" -eq 0 ] && break
    p=$((p + 1))
  done
done

have="$(find "$PAGES_DIR" -maxdepth 1 -type f -name 'year_*_p*.json' | wc -l | tr -d ' ')"
echo "[$(date -Is)] download done dataset=$DATASET_ID pages_fetched=$pages_fetched pages_on_disk=$have"
test "$have" -ge 5
