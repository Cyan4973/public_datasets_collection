#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="inspirehep_literature"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
DOWNLOAD_DIR="$REPO_ROOT/$DATA_DIR/downloads/$DATASET_ID"
PAGES_DIR="$DOWNLOAD_DIR/pages"
mkdir -p "$LOG_DIR" "$DOWNLOAD_DIR" "$PAGES_DIR"

RUN_TS="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="$LOG_DIR/download.$RUN_TS.log"
LATEST_LOG="$LOG_DIR/download.latest.log"
exec > >(tee "$LOG_FILE" "$LATEST_LOG") 2>&1

echo "[$(date -Is)] download start dataset=$DATASET_ID"

# One quantity family per bibliometric field; one sample per publication year.
# INSPIRE caps deep paging at size*page <= 10000, so we shard the crawl by year and
# cap pages per year. Each record is projected to a few scalar fields (no reference
# arrays), keeping the download small.
BASE="https://inspirehep.net/api/literature"
START_YEAR="${INSPIRE_START_YEAR:-1960}"
END_YEAR="${INSPIRE_END_YEAR:-2024}"
SIZE="${INSPIRE_SIZE:-1000}"
MAX_PAGES="${INSPIRE_MAX_PAGES:-5}"
# printf template; %s is replaced by the 4-digit year (SPIRES-style date search).
YEAR_QUERY="${INSPIRE_YEAR_QUERY:-date %s}"
FIELDS="${INSPIRE_FIELDS:-control_number,citation_count,author_count,number_of_pages,number_of_references,earliest_date,preprint_date}"
UA="openzl-public-datasets/1.0 (numeric dataset collection)"

fetch_page() {  # year page outfile -> writes JSON, echoes "<hits_on_page> <total>"
  local year="$1" page="$2" out="$3"
  local qstr; qstr="$(printf "$YEAR_QUERY" "$year")"
  curl --globoff -fsSL --retry 4 --retry-delay 3 --max-time 180 \
    -A "$UA" -H "Accept: application/json" -G \
    --data-urlencode "q=$qstr" \
    --data-urlencode "fields=$FIELDS" \
    --data-urlencode "sort=mostrecent" \
    --data-urlencode "size=$SIZE" \
    --data-urlencode "page=$page" \
    -o "$out" "$BASE"
  python3 - "$out" <<'PY'
import json, sys
try:
    d = json.load(open(sys.argv[1], encoding="utf-8"))
    hits = d["hits"]["hits"]
    total = d["hits"]["total"]
    total = total.get("value", total) if isinstance(total, dict) else total
except Exception as e:
    print(f"PARSE_ERROR {e}", file=sys.stderr)
    sys.exit(3)
print(f"{len(hits)} {int(total)}")
PY
}

# ---- fail-fast page-0 guard: validate query syntax / connectivity on a busy year ----
PROBE_OUT="$PAGES_DIR/year${END_YEAR}_p1.json"
if [ ! -s "$PROBE_OUT" ]; then
  echo "probe year=$END_YEAR page=1"
  if ! read -r phits ptotal < <(fetch_page "$END_YEAR" 1 "$PROBE_OUT"); then
    echo "FATAL: probe request failed (network or query). Check INSPIRE_YEAR_QUERY."
    rm -f "$PROBE_OUT"; exit 1
  fi
  if [ "${ptotal:-0}" -le 0 ]; then
    echo "FATAL: probe for year=$END_YEAR returned total=$ptotal."
    echo "       The year query '$(printf "$YEAR_QUERY" "$END_YEAR")' likely uses wrong syntax."
    rm -f "$PROBE_OUT"; exit 1
  fi
  echo "probe ok: hits_on_page=$phits total_for_year=$ptotal"
  sleep 0.6
fi

# ---- main crawl ----------------------------------------------------------------------
years_fetched=0
pages_fetched=0
for year in $(seq "$START_YEAR" "$END_YEAR"); do
  got_any=0
  for page in $(seq 1 "$MAX_PAGES"); do
    out="$PAGES_DIR/year${year}_p${page}.json"
    if [ -s "$out" ]; then
      got_any=1
      # inspect cached page to decide whether more pages exist
      n="$(python3 - "$out" <<'PY'
import json,sys
try: print(len(json.load(open(sys.argv[1]))["hits"]["hits"]))
except Exception: print(0)
PY
)"
      [ "$n" -lt "$SIZE" ] && break || continue
    fi
    if ! read -r hits total < <(fetch_page "$year" "$page" "$out"); then
      echo "WARN: fetch failed year=$year page=$page (stopping this year)"
      rm -f "$out"; break
    fi
    pages_fetched=$((pages_fetched + 1))
    got_any=1
    [ "$page" -eq 1 ] && echo "year=$year total=$total"
    sleep 0.6
    [ "$hits" -lt "$SIZE" ] && break   # last page for this year
  done
  [ "$got_any" -eq 1 ] && years_fetched=$((years_fetched + 1))
done

have="$(find "$PAGES_DIR" -maxdepth 1 -type f -name '*.json' | wc -l | tr -d ' ')"
echo "[$(date -Is)] download done dataset=$DATASET_ID years=$years_fetched pages_fetched=$pages_fetched pages_on_disk=$have"
test "$have" -ge 5
